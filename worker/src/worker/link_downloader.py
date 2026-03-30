"""Download link content via SSH to EC2 running y link download."""

import hashlib
import json
import os

import boto3
from loguru import logger

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from storage.service import link as link_service

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}
    async def execute(self, arguments):
        pass


def _s3_key_for_url(link_id: str, url: str) -> str:
    """Generate S3 key. Use url hash for activity-level (url != base_url)."""
    base_url = url.split('?')[0].split('#')[0]
    if url.split('#')[0] != base_url:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"links/{link_id}/{url_hash}/content.md"
    return f"links/{link_id}/content.md"


async def run_link_download(user_id: int, link_id: str, url: str):
    """SSH to EC2 and run y link download to fetch content via opencli."""
    link_service.update_download_status(link_id, "downloading", url=url)

    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        output = await runner.run_cmd(
            ["y", "link", "download", url],
            timeout=300,
        )
        logger.info("y link download output (truncated): {}", output[:200])

        result = json.loads(output.strip())
        if result.get("status") == "done":
            content = result.get("content", "")
            s3_key = _s3_key_for_url(link_id, url)
            s3 = boto3.client("s3")
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )
            link_service.update_download_status(
                link_id, "done", content_key=s3_key, url=url
            )
            if result.get("title"):
                link_service.update_link_title(link_id, result["title"])
        else:
            link_service.update_download_status(link_id, "failed", url=url)

    except Exception as e:
        logger.exception("Link download failed: {}", e)
        link_service.update_download_status(link_id, "failed", url=url)
        raise
