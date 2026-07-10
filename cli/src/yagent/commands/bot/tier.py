"""Shared helper for resolving a ref/pointer bot's effective display tier."""

from typing import Callable, Optional
from storage.entity.dto import BotConfig

MAX_DEREF_DEPTH = 5


def display_tier(bot_cfg: BotConfig, resolve_ref: Callable[[str], Optional[BotConfig]]) -> str:
    """Return the tier to display for `bot_cfg`.

    Non-ref bots use the routing `tier_of()` semantics (NULL -> tier3). Ref
    bots are excluded from tier pools by routing, so their own tier field is
    never consulted there; display the deref target's effective tier instead,
    following the ref chain up to `MAX_DEREF_DEPTH` hops with a cycle guard.
    `resolve_ref(name)` looks up a bot config by name, returning None if
    missing.
    """
    current = bot_cfg
    visited = set()
    while current.ref_bot_name:
        if current.name in visited or len(visited) >= MAX_DEREF_DEPTH:
            return "-"
        visited.add(current.name)
        target = resolve_ref(current.ref_bot_name)
        if target is None:
            return "-"
        current = target
    return current.tier or "tier3"
