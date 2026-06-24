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


def get_config_by_work_dir(user_id: int, work_dir: str) -> Optional[VmConfig]:
    return vm_repo.get_config_by_work_dir(user_id, work_dir)


def update_last_up(user_id: int, name: str, last_up: int) -> None:
    vm_repo.update_last_up(user_id, name, last_up)


def update_last_up_by_id(config_id: int, last_up: int) -> None:
    vm_repo.update_last_up_by_id(config_id, last_up)


def delete_config(user_id: int, name: str = "default") -> bool:
    return vm_repo.delete_config(user_id, name)
