from typing import Dict
from agent.tool_base import Tool


class BashTool(Tool):
    name = "bash"
    description = "Run a shell command and return stdout and stderr."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    }

    async def execute(self, arguments: Dict) -> str:
        command = arguments["command"]
        try:
            result = await self.run_cmd(cmd=["bash", "-c", command])
            return result or "(no output)"
        except Exception as e:
            return f"Error running command: {e}"
