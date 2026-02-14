from typing import Dict
from agent.tool_base import Tool


class FileEditTool(Tool):
    name = "file_edit"
    description = (
        "Edit a file by replacing an exact string match with new content. "
        "The old_string must match exactly (including whitespace/indentation). "
        "Provide enough context in old_string to make it unique in the file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file path to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace. Must be unique in the file.",
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def execute(self, arguments: Dict) -> str:
        path = arguments["path"]
        old_string = arguments["old_string"]
        new_string = arguments["new_string"]

        try:
            content = await self.run_cmd(cmd=["cat", path])
        except Exception as e:
            return f"Error reading file: {e}"

        if old_string == new_string:
            return "Error: old_string and new_string are identical."

        count = content.count(old_string)
        if count == 0:
            return "Error: old_string not found in file."
        if count > 1:
            return f"Error: old_string matches {count} locations. Provide more context to make it unique."

        new_content = content.replace(old_string, new_string, 1)
        try:
            await self.run_cmd(cmd=["tee", path], stdin=new_content)
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error writing file: {e}"
