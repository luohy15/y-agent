"""VM configuration service."""

from typing import Optional
from storage.entity.dto import VmConfig
from storage.repository import vm_config as vm_repo


def get_config(user_id: int) -> Optional[VmConfig]:
    return vm_repo.get_config(user_id)


def set_config(user_id: int, config: VmConfig) -> VmConfig:
    return vm_repo.set_config(user_id, config)


def delete_config(user_id: int) -> bool:
    return vm_repo.delete_config(user_id)
