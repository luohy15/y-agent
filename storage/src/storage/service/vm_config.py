"""VM configuration service."""

from typing import List, Optional
from storage.entity.dto import VmConfig
from storage.repository import vm_config as vm_repo


def list_configs(user_id: int) -> List[VmConfig]:
    return vm_repo.list_configs(user_id)


def get_config(user_id: int, name: str = "default") -> Optional[VmConfig]:
    return vm_repo.get_config(user_id, name)


def set_config(user_id: int, config: VmConfig) -> VmConfig:
    return vm_repo.set_config(user_id, config)


def delete_config(user_id: int, name: str = "default") -> bool:
    return vm_repo.delete_config(user_id, name)
