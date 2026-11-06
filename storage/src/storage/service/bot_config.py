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
    degrades to a tier2 fallback instead of resolving the disabled bot).

    Writes only the `enabled` column on the existing owner/name row: never
    inserts, and never rewrites unrelated fields via a full-config round trip.
    Returns False when the row is absent; True when it exists, including a
    no-op when the value is already desired.
    """
    return bot_repo.set_enabled(user_id, name, enabled)


def set_effort_capability(user_id: int, name: str, levels: Optional[List[str]], evidence: Optional[str]) -> bool:
    from storage.dto.bot import EFFORT_LEVELS

    if levels is not None:
        if (not isinstance(levels, list) or not levels
                or any(not isinstance(level, str) or level not in EFFORT_LEVELS for level in levels)):
            raise ValueError("effort levels must be a nonempty list of low, medium, high, xhigh, max")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("effort capability requires evidence")
        levels = list(dict.fromkeys(levels))
        evidence = evidence.strip()
    return bot_repo.set_effort_capability(user_id, name, levels, evidence)


def set_sub_ref(user_id: int, name: str, target: Optional[str]) -> bool:
    """Set or clear a pointer's subscription target.

    The row must already be a pointer. A target must exist for the same owner,
    be enabled, not itself be a pointer, and carry a nonempty subscription map.
    None clears the column. Full upserts never write it.
    """
    from storage.dto.bot import subscription_tiers_of

    pointer = bot_repo.get_config(user_id, name)
    if pointer is None:
        return False
    if not pointer.ref_bot_name:
        raise ValueError(f"bot {name!r} is not a pointer")
    if target is not None:
        if target == name:
            raise ValueError(f"bot {name!r} cannot reference itself")
        dest = bot_repo.get_config(user_id, target)
        if dest is None:
            raise ValueError(f"subscription ref target {target!r} not found")
        if not dest.enabled:
            raise ValueError(f"subscription ref target {target!r} is disabled")
        if dest.ref_bot_name:
            raise ValueError(f"subscription ref target {target!r} is a pointer")
        if not subscription_tiers_of(dest):
            raise ValueError(f"subscription ref target {target!r} has no subscription tiers")
    return bot_repo.set_sub_ref(user_id, name, target)


def set_subscription_tiers(user_id: int, name: str, tiers: Optional[dict[str, Optional[float]]]) -> bool:
    from storage.dto.bot import normalize_tier_weights

    if tiers is not None:
        tiers = normalize_tier_weights(tiers)
    return bot_repo.set_subscription_tiers(user_id, name, tiers)


def delete_config(user_id: int, name: str) -> bool:
    if name == "default":
        return False
    return bot_repo.delete_config(user_id, name)


def rename_config(user_id: int, old_name: str, new_name: str) -> bool:
    """Rename a bot config, cascading to `bot_config.ref_bot_name` and
    `sub_ref_bot_name` pointers and `chat.bot_name`. See
    `bot_config_repo.rename_config` for the validation rules (existence,
    name collision, "default" guard)."""
    if not bot_repo.rename_config(user_id, old_name, new_name):
        return False
    chat_repo.rename_bot_name(user_id, old_name, new_name)
    return True


def select_weighted_round_robin(user_id: int, tier: str, candidates: List[tuple[str, float]]) -> Optional[str]:
    return bot_route_state.select_weighted_round_robin(user_id, tier, candidates)
