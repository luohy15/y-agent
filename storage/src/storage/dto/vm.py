from dataclasses import dataclass, asdict
from typing import Dict, Optional

@dataclass
class VmConfig:
    id: Optional[int] = None
    name: str = "default"
    api_token: str = ""
    vm_name: str = ""
    work_dir: str = ""
    ec2_instance_id: str = ""
    ec2_region: str = ""
    last_up: Optional[int] = None  # unix timestamp

    @classmethod
    def from_dict(cls, data: Dict) -> 'VmConfig':
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
