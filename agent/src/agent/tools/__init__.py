from typing import Dict, List, Optional
from storage.entity.dto import VmConfig
from agent.tool_base import Tool
from agent.tools.file_read import FileReadTool
from agent.tools.file_write import FileWriteTool
from agent.tools.file_edit import FileEditTool
from agent.tools.bash import BashTool


def get_tools(vm_config: Optional[VmConfig] = None) -> List[Tool]:
    return [FileReadTool(vm_config), FileWriteTool(vm_config), FileEditTool(vm_config), BashTool(vm_config)]


def get_tools_map(vm_config: Optional[VmConfig] = None) -> Dict[str, Tool]:
    return {t.name: t for t in get_tools(vm_config)}


def get_openai_tools(vm_config: Optional[VmConfig] = None) -> List[Dict]:
    return [t.to_openai_tool() for t in get_tools(vm_config)]
