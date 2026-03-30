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


async def run_link_download(user_id: int, link_id: str, url: str):
    """SSH to EC2 and run y link download to fetch content via opencli."""
    link_service.update_download_status(link_id, "downloading")

    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        output = await runner.run_cmd(
            ["y", "link", "download", url, "--link-id", link_id],
            timeout=300,
        )
        logger.info("y link download output: {}", output)

        result = json.loads(output.strip())
        if result.get("status") == "done":
            link_service.update_download_status(
                link_id, "done", content_key=result.get("content_key")
            )
            if result.get("title"):
                link_service.update_link_title(link_id, result["title"])
        else:
            link_service.update_download_status(link_id, "failed")

    except Exception as e:
        logger.exception("Link download failed: {}", e)
        link_service.update_download_status(link_id, "failed")
        raise
