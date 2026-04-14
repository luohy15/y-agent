"""Download link content via SSH to EC2 running y link download."""

import json

from loguru import logger

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from storage.service import link as link_service


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}
    async def execute(self, arguments):
        pass


def _content_path(link_id: str, activity_id: str = None) -> str:
    """Generate relative content path. Use activity_id for activity-level content."""
    if activity_id:
        return f"links/{link_id}/{activity_id}/content.md"
    return f"links/{link_id}/content.md"


async def run_link_download(user_id: int, link_id: str, url: str, activity_id: str = None):
    """SSH to EC2 and run y link download to fetch content via opencli."""
    url = url.split('#')[0]  # strip fragment
    link_service.update_download_status(link_id, "downloading", url=url)

    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        content_key = _content_path(link_id, activity_id)
        output = await runner.run_cmd(
            ["y", "link", "download", url, "--save", content_key],
            timeout=300,
        )
        logger.info("y link download output (truncated): {}", output[:200])

        result = json.loads(output.strip())
        if result.get("status") == "done":
            link_service.update_download_status(
                link_id, "done", content_key=content_key, url=url
            )
            if result.get("title"):
                link_service.update_link_title(link_id, result["title"])
        else:
            link_service.update_download_status(link_id, "failed", url=url)

    except Exception as e:
        logger.exception("Link download failed: {}", e)
        link_service.update_download_status(link_id, "failed", url=url)
        raise
