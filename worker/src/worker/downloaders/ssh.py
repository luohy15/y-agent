"""SSH downloader: run `y fetch get --json <url>` on the user's VM and return markdown."""

import json

from loguru import logger

from agent.config import resolve_vm_config
from agent.tool_base import Tool


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def download(user_id: int, url: str, timeout: int = 300) -> dict:
    """Run `y fetch get --json <url>` via SSH on the user's VM; return content in memory."""
    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        output = await runner.run_cmd(
            ["y", "fetch", "get", "--json", url],
            timeout=timeout,
        )
        logger.info("ssh y fetch get output (truncated): {}", output[:200])
        result = json.loads(output.strip())
        status = result.get("status", "failed")
        return {
            "status": "done" if status == "done" else "failed",
            "title": result.get("title") or None,
            "content": result.get("content"),
            "method_used": "ssh",
            "error": result.get("error") if status != "done" else None,
        }
    except Exception as e:
        logger.exception("ssh download failed: {}", e)
        return {
            "status": "failed",
            "title": None,
            "content": None,
            "method_used": "ssh",
            "error": str(e),
        }
