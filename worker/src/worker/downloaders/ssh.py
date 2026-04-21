"""SSH helpers for link content storage on the remote VM.

`$Y_AGENT_HOME` is not exported in the VM's non-interactive shell, so we apply
the same default as the Python CLI (`~/.y-agent`) via `${Y_AGENT_HOME:-$HOME/.y-agent}`.
"""

import json

from loguru import logger

from agent.config import resolve_vm_config
from agent.tool_base import Tool


_RESOLVE_HOME = '"${Y_AGENT_HOME:-$HOME/.y-agent}"'


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
    """Write `content` to `${Y_AGENT_HOME:-$HOME/.y-agent}/<content_key>` on the remote VM."""
    vm_config = resolve_vm_config(user_id)
    runner = _CmdRunner(vm_config)
    safe_path = content_key.replace("'", "'\\''")
    script = (
        f"target={_RESOLVE_HOME}\"/{safe_path}\"; "
        "mkdir -p \"$(dirname \"$target\")\" && cat > \"$target\""
    )
    await runner.run_cmd(["sh", "-c", script], stdin=content, timeout=timeout)
