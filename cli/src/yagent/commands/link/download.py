import hashlib
import json
import subprocess
import sys

import click


def _get_opencli_cmd(url: str, output_dir: str) -> list[str]:
    """Determine the opencli command based on URL domain."""
    opencli = "/opt/homebrew/bin/opencli"
    if "mp.weixin.qq.com" in url:
        return [opencli, "weixin", "download", "--url", url, "--output", output_dir, "--download-images", "false"]
    elif "youtube.com" in url or "youtu.be" in url:
        return [opencli, "youtube", "transcript", url, "-f", "json"]
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

        # For youtube transcript, output is in stdout (json format)
        if "youtube.com" in url or "youtu.be" in url:
            content = result.stdout
            title = ""
            try:
                yt_data = json.loads(content)
                if isinstance(yt_data, list) and yt_data:
                    title = yt_data[0].get("title", "")
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
