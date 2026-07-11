"""Shared configuration helpers for CLI and worker."""

import logging
import os
import random
from typing import List, Optional

from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import vm_config as vm_service
from storage.service.user import get_default_user_id

logger = logging.getLogger(__name__)

_MAX_REF_DEPTH = 5


def _effective_backend(bot_config: BotConfig) -> str:
    return bot_config.backend or bot_config.api_type


# --- Tier helpers ---

def tier_of(bot_config: BotConfig) -> str:
    """Return the tier for a bot config.

    Explicit bot_config.tier wins; NULL/unspecified defaults to tier3
    (most bots are tier3, so unlabeled configs need no explicit tier).
    """
    return bot_config.tier or "tier3"


def _deref_bot_config(user_id: int, bot_config: BotConfig, visited: Optional[set] = None, depth: int = 0) -> BotConfig:
    """Recursively dereference a ref bot to its target config.

    If bot_config.ref_bot_name is set, resolve it to the target bot config.
    Returns the original config if ref_bot_name is not set.
    Raises ValueError on circular refs or max depth exceeded.
    """
    if not bot_config.ref_bot_name:
        return bot_config

    if depth >= _MAX_REF_DEPTH:
        raise ValueError(
            f"Max ref depth ({_MAX_REF_DEPTH}) exceeded resolving bot '{bot_config.name}'"
        )

    visited = visited or set()
    ref_name = bot_config.ref_bot_name
    if ref_name in visited:
        raise ValueError(
            f"Circular ref detected: {bot_config.name} -> {ref_name} (already visited)"
        )
    visited.add(ref_name)

    target = bot_service.get_config(user_id, ref_name)
    if not target:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            target = bot_service.get_config(default_user_id, ref_name)
    if not target:
        raise ValueError(
            f"Ref target bot '{ref_name}' not found (resolving '{bot_config.name}')"
        )

    return _deref_bot_config(user_id, target, visited, depth + 1)


def _universe(user_id: int) -> List[BotConfig]:
    """Return the candidate pool a dispatch request is resolved against.

    User's own configs, falling back to the system default user's configs
    only when the user has none of their own. Ref/pointer bots and
    type='model' bots are never routing candidates; disabled bots are out
    (an explicit name pin to a disabled bot degrades to tier2, see
    resolve_bot_config). Perplexity stays in the universe here (it is only
    excluded from tier-filter candidacy) so backend=perplexity / name=px
    pins still resolve.
    """
    configs = bot_service.list_configs(user_id)
    if not configs:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            configs = bot_service.list_configs(default_user_id)
    return [
        cfg for cfg in configs
        if cfg.enabled
        and not cfg.ref_bot_name
        and (getattr(cfg, "type", None) or "agent") != "model"
    ]


def _candidates(universe: List[BotConfig], bot_name: str = None, backend: str = None, tier: str = None) -> List[BotConfig]:
    """Intersect the universe with the given filters.

    Filters combine with AND, not precedence: bot_name, backend, and tier
    each narrow the pool further when given. The tier filter additionally
    excludes perplexity (web-search bot is pin-only, not a pool member).
    """
    result = universe
    if bot_name:
        result = [cfg for cfg in result if cfg.name == bot_name]
    if backend:
        result = [cfg for cfg in result if _effective_backend(cfg) == backend]
    if tier:
        result = [cfg for cfg in result if tier_of(cfg) == tier and _effective_backend(cfg) != "perplexity"]
    return result


def _pick_by_weight(bots: List[BotConfig]) -> Optional[BotConfig]:
    """Weighted random pick from bots by route_weight.

    Probability = route_weight / sum(route_weights). Bots with
    route_weight <= 0 are excluded from the draw. Only called with 2+
    candidates (see _select) so weight never gates a sole candidate.
    """
    eligible = [(cfg, cfg.route_weight) for cfg in bots if cfg.route_weight and cfg.route_weight > 0]
    if not eligible:
        return None
    choices, raw_weights = zip(*eligible)
    total = sum(raw_weights)
    weights = [w / total for w in raw_weights]
    return random.choices(choices, weights=weights, k=1)[0]


def _select(candidates: List[BotConfig], user_id: int = None, tier: str = None) -> Optional[BotConfig]:
    """Pick a config from a candidate pool.

    A sole candidate is used directly regardless of its weight; a
    multi-candidate tier pool uses persisted smooth weighted round-robin;
    other multi-candidate pools draw by weight. Both may come up empty if
    every candidate has zero/unset weight.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if user_id is not None and tier:
        selected_name = bot_service.select_weighted_round_robin(
            user_id,
            tier,
            [(cfg.name, cfg.route_weight) for cfg in candidates if cfg.route_weight and cfg.route_weight > 0],
        )
        if selected_name:
            return next(cfg for cfg in candidates if cfg.name == selected_name)
        return None
    return _pick_by_weight(candidates)


def _global_default(user_id: int) -> BotConfig:
    bot_config = bot_service.get_config(user_id)
    if not bot_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            bot_config = bot_service.get_config(default_user_id)
    if not bot_config:
        raise ValueError(f"No bot config found for user_id={user_id}")
    return _deref_bot_config(user_id, bot_config)


def resolve_bot_config(user_id: int, bot_name: str = None, backend: str = None, tier: str = None) -> BotConfig:
    """Resolve a dispatch request to a bot config.

    Unified filter resolution (no precedence chain): bot_name / backend /
    tier intersect over the user's universe of eligible configs. Exactly
    one match is used directly; multiple tier matches use persisted smooth
    weighted round-robin. No
    filters, or an empty intersection, re-resolves against the tier2 pool;
    an empty tier2 pool falls back to the user's global default bot.
    """
    universe = _universe(user_id)

    if bot_name or backend or tier:
        selected = _select(
            _candidates(universe, bot_name=bot_name, backend=backend, tier=tier),
            user_id=user_id if tier else None,
            tier=tier,
        )
        if not selected and bot_name and not backend and not tier:
            # Explicit name pins keep pointer-deref semantics even though
            # ref bots are excluded from the universe: name addressing
            # (story 20 aliasing) should still reach the pointer's target.
            pinned = bot_service.get_config(user_id, bot_name)
            if pinned and pinned.ref_bot_name and pinned.enabled:
                selected = _deref_bot_config(user_id, pinned)
        if selected:
            return selected
        logger.warning(
            "No bot matched filters (bot_name=%s backend=%s tier=%s) for user_id=%s; falling back to tier2",
            bot_name, backend, tier, user_id,
        )

    tier2 = _select(_candidates(universe, tier="tier2"), user_id=user_id, tier="tier2")
    if tier2:
        return tier2

    logger.warning("Empty tier2 pool for user_id=%s; falling back to default bot", user_id)
    return _global_default(user_id)


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
