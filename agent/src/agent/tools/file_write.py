import os
from typing import Dict
from agent.tool_base import Tool


class FileWriteTool(Tool):
    name = "file_write"
    description = "Write content to a file at the given path. Creates parent directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file path to write to.",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, arguments: Dict) -> str:
        path = arguments["path"]
        content = arguments["content"]
        try:
            dirname = os.path.dirname(path)
            if dirname:
                await self.run_cmd(cmd=["mkdir", "-p", dirname])
            await self.run_cmd(cmd=["tee", path], stdin=content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"
