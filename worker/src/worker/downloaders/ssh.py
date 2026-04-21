"""SSH downloader — runs `y link download` on the opencli VM via SSH.

Saves the markdown directly to `$Y_AGENT_HOME/<content_key>` on the remote side,
so the return dict does not carry the `content` body.
"""

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


async def download(user_id: int, url: str, content_key: str, timeout: int = 300) -> dict:
    """Run `y link download <url> --save <content_key>` via SSH on the user's VM."""
    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        output = await runner.run_cmd(
            ["y", "link", "download", url, "--save", content_key],
            timeout=timeout,
        )
        logger.info("ssh y link download output (truncated): {}", output[:200])
        result = json.loads(output.strip())
        status = result.get("status", "failed")
        return {
            "status": "done" if status == "done" else "failed",
            "title": result.get("title") or None,
            "content": None,
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


async def save_content_remote(user_id: int, content_key: str, content: str, timeout: int = 60) -> None:
    """Write `content` to `$Y_AGENT_HOME/<content_key>` on the remote VM via SSH stdin."""
    vm_config = resolve_vm_config(user_id)
    runner = _CmdRunner(vm_config)
    # Use single-quoted shell path; content_key is server-controlled, no shell metachars expected.
    safe_path = content_key.replace("'", "'\\''")
    script = (
        f"target=\"$Y_AGENT_HOME/{safe_path}\"; "
        "mkdir -p \"$(dirname \"$target\")\" && cat > \"$target\""
    )
    await runner.run_cmd(["sh", "-c", script], stdin=content, timeout=timeout)
