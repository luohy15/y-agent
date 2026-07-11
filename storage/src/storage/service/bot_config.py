"""Bot configuration service."""

from typing import List, Optional
from storage.entity.dto import BotConfig
from storage.repository import bot_config as bot_repo
from storage.repository import chat as chat_repo
from storage.service import bot_route_state


def list_configs(user_id: int) -> List[BotConfig]:
    return bot_repo.list_configs(user_id)


def get_config(user_id: int, name: str = "default") -> Optional[BotConfig]:
    return bot_repo.get_config(user_id, name=name)


def add_config(user_id: int, config: BotConfig) -> BotConfig:
    return bot_repo.add_config(user_id, config)


def set_enabled(user_id: int, name: str, enabled: bool) -> bool:
    """Enable or disable a bot config. Disabled bots are excluded from the
    dispatch universe entirely, including an explicit name pin (which
    degrades to a tier2 fallback instead of resolving the disabled bot)."""
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


def rename_config(user_id: int, old_name: str, new_name: str) -> bool:
    """Rename a bot config, cascading to `bot_config.ref_bot_name` pointers
    and `chat.bot_name`. See `bot_config_repo.rename_config` for the
    validation rules (existence, name collision, "default" guard)."""
    if not bot_repo.rename_config(user_id, old_name, new_name):
        return False
    chat_repo.rename_bot_name(user_id, old_name, new_name)
    return True


def select_weighted_round_robin(user_id: int, tier: str, candidates: List[tuple[str, float]]) -> Optional[str]:
    return bot_route_state.select_weighted_round_robin(user_id, tier, candidates)
