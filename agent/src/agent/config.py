"""Shared configuration helpers for CLI and worker."""

import os

from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import vm_config as vm_service
from storage.service.user import get_default_user_id


def resolve_bot_config(user_id: int, bot_name: str = None) -> BotConfig:
    bot_config = None
    if bot_name:
        bot_config = bot_service.get_config(user_id, bot_name)
    if not bot_config:
        bot_config = bot_service.get_config(user_id)
    if not bot_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            bot_config = bot_service.get_config(default_user_id)
    if not bot_config:
        raise ValueError(f"No bot config found for user_id={user_id}, bot_name={bot_name}")
    return bot_config


def resolve_vm_config(user_id: int, vm_name: str = None, work_dir: str = None) -> VmConfig:
    vm_config = None
    if vm_name:
        vm_config = vm_service.get_config(user_id, vm_name)
    if not vm_config and work_dir:
        vm_config = vm_service.get_config_by_work_dir(user_id, work_dir)
    if not vm_config:
        vm_config = vm_service.get_config(user_id, "default")
    if not vm_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            vm_config = vm_service.get_config(default_user_id, "default")
    if not vm_config:
        vm_config = VmConfig()
        vm_config.work_dir = os.environ.get("VM_WORK_DIR_CLI", "")
    if work_dir:
        vm_config.work_dir = work_dir
    return vm_config
