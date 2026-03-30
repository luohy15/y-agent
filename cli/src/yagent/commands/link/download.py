import json
import os
import subprocess
import sys

import boto3
import click

from yagent.settings import load_config


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
@click.option("--link-id", required=True, help="Link ID for S3 storage path")
def link_download(url: str, link_id: str):
    """Download a URL's content via opencli and store to S3."""
    cfg = load_config()
    s3_bucket = cfg.get("s3_bucket", "")

    output_dir = f"/tmp/link-dl-{link_id}"

    try:
        opencli_cmd = _get_opencli_cmd(url, output_dir)
        cmd_str = " ".join(f"'{c}'" for c in opencli_cmd)

        # SSH to opencli and run the command
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

        # Upload to S3
        s3_key = f"links/{link_id}/content.md"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
        )

        click.echo(json.dumps({
            "status": "done",
            "content_key": s3_key,
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
