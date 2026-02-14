"""Shared configuration helpers for CLI and worker."""

from storage.entity.dto import BotConfig
from storage.service import bot_config as bot_service

from agent.provider import OpenAIFormatProvider, AnthropicFormatProvider
from agent.skills import discover_skills, skills_to_prompt


def build_system_prompt() -> str:
    skills_block = skills_to_prompt(discover_skills())
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
    return bot_config
