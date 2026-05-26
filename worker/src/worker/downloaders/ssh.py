"""SSH downloader: run `y link fetch --json <url>` on the user's VM and return markdown."""

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


async def download(user_id: int, url: str, timeout: int = 300, link_id: str | None = None, activity_id: str | None = None) -> dict:
    """Run `y link fetch --json <url>` via SSH on the user's VM; return content in memory."""
    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        cmd = ["y", "link", "fetch", "--json"]
        if link_id:
            cmd.extend(["--link-id", link_id])
        if activity_id:
            cmd.extend(["--activity-id", activity_id])
        cmd.append(url)
        output = await runner.run_cmd(
            cmd,
            timeout=timeout,
        )
        logger.info("ssh y link fetch output (truncated): {}", output[:200])
        result = json.loads(output.strip())
        status = result.get("status", "failed")
        return {
            "status": "done" if status == "done" else "failed",
            "title": result.get("title") or None,
            "content": result.get("content"),
            "path": result.get("path"),
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
