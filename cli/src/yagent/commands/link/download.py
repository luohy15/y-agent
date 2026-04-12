import hashlib
import json
import re
import subprocess
import sys

import click


def _get_article_cmd(url: str) -> list[str]:
    """Get the opencli twitter article command."""
    return ["/opt/homebrew/bin/opencli", "twitter", "article", url, "-f", "json"]


def _get_opencli_cmd(url: str, output_dir: str) -> list[str]:
    """Determine the opencli command based on URL domain."""
    opencli = "/opt/homebrew/bin/opencli"
    if "mp.weixin.qq.com" in url:
        return [opencli, "weixin", "download", "--url", url, "--output", output_dir, "--download-images", "false"]
    elif "youtube.com" in url or "youtu.be" in url:
        return [opencli, "youtube", "transcript", url, "-f", "json"]
    elif "bilibili.com" in url:
        bv_match = re.search(r'(BV[a-zA-Z0-9]+)', url)
        if bv_match:
            return [opencli, "bilibili", "subtitle", "-f", "json", bv_match.group(1)]
        else:
            raise ValueError(f"Cannot extract BV number from URL: {url}")
    elif "twitter.com" in url or "x.com/" in url:
        return [opencli, "twitter", "thread", url, "-f", "json", "--limit", "1"]
    else:
        return [opencli, "web", "read", "--url", url, "--output", output_dir, "--download-images", "false"]


@click.command("download")
@click.argument("url")
def link_download(url: str):
    """Download a URL's content via opencli and output JSON result to stdout."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    output_dir = f"/tmp/link-dl-{url_hash}"

    try:
        opencli_cmd = _get_opencli_cmd(url, output_dir)
        cmd_str = " ".join(f"'{c}'" for c in opencli_cmd)

        # SSH to opencli and run the command (prepend PATH for non-interactive shell)
        cmd_str = f"export PATH=/opt/homebrew/bin:$PATH; {cmd_str}"
        result = subprocess.run(
            ["ssh", "opencli", cmd_str],
            capture_output=True,
            text=True,
            timeout=240,
        )

        if result.returncode != 0:
            click.echo(json.dumps({
                "status": "failed",
                "error": result.stderr[:500] if result.stderr else "opencli command failed",
            }))
            sys.exit(1)

        # For bilibili subtitle, output is in stdout (json format)
        if "bilibili.com" in url:
            title = ""
            try:
                bili_data = json.loads(result.stdout)
                if isinstance(bili_data, list):
                    content = "\n".join(item.get("content", "") for item in bili_data if item.get("content"))
                else:
                    content = result.stdout
            except (json.JSONDecodeError, KeyError, IndexError):
                content = result.stdout
        # For youtube transcript, output is in stdout (json format)
        elif "youtube.com" in url or "youtu.be" in url:
            content = result.stdout
            title = ""
            try:
                yt_data = json.loads(content)
                if isinstance(yt_data, list) and yt_data:
                    title = yt_data[0].get("title", "")
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        elif "twitter.com" in url or "x.com/" in url:
            # thread command returns JSON array; extract only the original post
            title = ""
            content = result.stdout
            try:
                tweets = json.loads(result.stdout)
                if isinstance(tweets, list) and tweets:
                    post_text = tweets[0].get("text", "").strip()
                    # If post text is just a t.co link, it's likely an article — try article command
                    if post_text.startswith("https://t.co/") and "\n" not in post_text:
                        article_cmd = _get_article_cmd(url)
                        article_cmd_str = " ".join(f"'{c}'" for c in article_cmd)
                        article_cmd_str = f"export PATH=/opt/homebrew/bin:$PATH; {article_cmd_str}"
                        article_result = subprocess.run(
                            ["ssh", "opencli", article_cmd_str],
                            capture_output=True, text=True, timeout=240,
                        )
                        if article_result.returncode == 0 and article_result.stdout.strip():
                            try:
                                articles = json.loads(article_result.stdout)
                                if isinstance(articles, list) and articles:
                                    article = articles[0]
                                    title = article.get("title", "")
                                    content = article.get("content", article_result.stdout)
                                else:
                                    content = article_result.stdout
                            except (json.JSONDecodeError, KeyError, IndexError):
                                content = article_result.stdout
                        else:
                            content = post_text
                    else:
                        content = post_text
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        else:
            # For web/read and weixin/download, output is saved to file on opencli machine
            # Read the markdown file via SSH
            find_result = subprocess.run(
                ["ssh", "opencli", f"find '{output_dir}' -name '*.md' -type f | head -1"],
                capture_output=True, text=True, timeout=10,
            )
            md_path = find_result.stdout.strip()
            if not md_path:
                click.echo(json.dumps({
                    "status": "failed",
                    "error": "No markdown file found in output directory",
                }))
                sys.exit(1)

            cat_result = subprocess.run(
                ["ssh", "opencli", f"cat '{md_path}'"],
                capture_output=True, text=True, timeout=30,
            )
            content = cat_result.stdout
            title = ""

            # Clean up remote temp dir
            subprocess.run(
                ["ssh", "opencli", f"rm -rf '{output_dir}'"],
                capture_output=True, timeout=10,
            )

        if not content.strip():
            click.echo(json.dumps({
                "status": "failed",
                "error": "Empty content returned",
            }))
            sys.exit(1)

        click.echo(json.dumps({
            "status": "done",
            "content": content,
            "title": title,
        }))

    except subprocess.TimeoutExpired:
        click.echo(json.dumps({
            "status": "failed",
            "error": "Command timed out",
        }))
        sys.exit(1)
    except Exception as e:
        click.echo(json.dumps({
            "status": "failed",
            "error": str(e),
        }))
        sys.exit(1)
