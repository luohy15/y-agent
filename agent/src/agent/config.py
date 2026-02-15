"""Shared configuration helpers for CLI and worker."""

import os

from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import vm_config as vm_service
from storage.service.user import get_default_user_id

from agent.provider import OpenAIFormatProvider, AnthropicFormatProvider
from agent.skills import discover_skills, skills_to_prompt


async def build_system_prompt(vm_config: VmConfig | None = None) -> str:
    skills_block = skills_to_prompt(await discover_skills(vm_config=vm_config))
    return ("\n" + skills_block) if skills_block else ""


def make_provider(bot_config: BotConfig):
    if bot_config.api_type == "anthropic":
        return AnthropicFormatProvider(bot_config)
    return OpenAIFormatProvider(bot_config)


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


def resolve_vm_config(user_id: int) -> VmConfig | None:
    if os.environ.get("VM_BACKEND") != "remote":
        return None
    vm_config = vm_service.get_config(user_id)
    if not vm_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            vm_config = vm_service.get_config(default_user_id)
    if not vm_config:
        raise ValueError(f"No vm config found for user_id={user_id}")
    return vm_config
