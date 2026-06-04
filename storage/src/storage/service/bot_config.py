"""Bot configuration service."""

from typing import List, Optional
from storage.entity.dto import BotConfig
from storage.repository import bot_config as bot_repo


def list_configs(user_id: int) -> List[BotConfig]:
    return bot_repo.list_configs(user_id)


def get_config(user_id: int, name: str = "default") -> Optional[BotConfig]:
    return bot_repo.get_config(user_id, name=name)


def add_config(user_id: int, config: BotConfig) -> BotConfig:
    return bot_repo.add_config(user_id, config)


def set_enabled(user_id: int, name: str, enabled: bool) -> bool:
    """Enable or disable a bot config. Disabled bots are excluded from
    default routing but can still be explicitly pinned by name."""
    config = bot_repo.get_config(user_id, name=name)
    if config is None:
        return False
    config.enabled = enabled
    bot_repo.add_config(user_id, config)
    return True


def delete_config(user_id: int, name: str) -> bool:
    if name == "default":
        return False
    return bot_repo.delete_config(user_id, name)
