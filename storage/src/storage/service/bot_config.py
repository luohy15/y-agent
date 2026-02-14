"""Bot configuration service."""

from typing import List, Optional
from storage.entity.dto import BotConfig, DEFAULT_OPENROUTER_CONFIG
from storage.repository import bot_config as bot_repo


def list_configs(user_id: int) -> List[BotConfig]:
    return bot_repo.list_configs(user_id)


def get_config(user_id: int, name: str = "default") -> Optional[BotConfig]:
    return bot_repo.get_config(user_id, name=name)


def add_config(user_id: int, config: BotConfig) -> BotConfig:
    if config.name == "default":
        if config.openrouter_config is None:
            config.openrouter_config = DEFAULT_OPENROUTER_CONFIG.copy()
    return bot_repo.add_config(user_id, config)


def delete_config(user_id: int, name: str) -> bool:
    if name == "default":
        return False
    return bot_repo.delete_config(user_id, name)
