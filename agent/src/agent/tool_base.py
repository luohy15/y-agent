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
        work_dir = self.vm_config.work_dir if self.vm_config else None
        if not self.vm_config or not self.vm_config.api_token:
            from agent.tools.local_exec import local_exec
            return await local_exec(cmd, stdin, timeout, cwd=work_dir)
        if self.vm_config.vm_name and self.vm_config.vm_name.startswith("ssh:"):
            from agent.tools.ssh_exec import ssh_exec
            return await ssh_exec(self.vm_config, cmd, stdin, dir=work_dir or None, timeout=timeout)
        from agent.tools.sprites_exec import sprites_exec
        return await sprites_exec(self.vm_config, cmd, stdin, dir=work_dir or None, timeout=timeout)

    @abstractmethod
    async def execute(self, arguments: Dict) -> str:
        pass
