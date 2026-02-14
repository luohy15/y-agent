from abc import ABC, abstractmethod
from typing import Dict, Optional

from storage.entity.dto import VmConfig


class Tool(ABC):
    name: str
    description: str
    parameters: Dict  # JSON schema

    def __init__(self, vm_config: Optional[VmConfig] = None):
        self.vm_config = vm_config

    def to_openai_tool(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run_cmd(self, cmd: list[str], stdin: str | None = None, timeout: float = 30) -> str:
        if self.vm_config is None:
            from agent.tools.local_exec import local_exec
            return await local_exec(cmd, stdin, timeout)
        from agent.tools.sprites_exec import sprites_exec
        return await sprites_exec(self.vm_config, cmd, stdin, timeout=timeout)

    @abstractmethod
    async def execute(self, arguments: Dict) -> str:
        pass
