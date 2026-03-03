from dataclasses import dataclass, asdict
from typing import Dict

@dataclass
class VmConfig:
    name: str = "default"
    api_token: str = ""
    vm_name: str = ""
    work_dir: str = ""

    @classmethod
    def from_dict(cls, data: Dict) -> 'VmConfig':
        return cls(**data)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
