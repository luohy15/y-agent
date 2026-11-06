"""Shared configuration helpers for CLI and worker."""

import logging
import os
import random
from typing import List, Optional

from storage.dto.bot import TIERS, effective_effort_levels, subscription_tiers_of, tier_weight, tiers_of
from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import vm_config as vm_service
from storage.service.user import get_default_user_id

logger = logging.getLogger(__name__)

_MAX_REF_DEPTH = 5


class EffortCapabilityError(ValueError):
    """An explicit effort has no declaring bot. Callers must not fall back."""

    def __init__(self, effort: str, bot_name: str = None, declared: Optional[List[str]] = None):
        self.effort = effort
        self.bot_name = bot_name
        self.declared = declared
        if bot_name:
            message = f"bot {bot_name!r} does not declare reasoning effort {effort!r}"
        else:
            message = f"no runnable bot declares reasoning effort {effort!r}"
        if declared is not None:
            shown = ", ".join(declared) if declared else "none"
            message += f" (declared: {shown})"
        super().__init__(message)


class VmConfigError(ValueError):
    """A generic VM command named a chat-only node.

    Chat execution resolves nodes through `agent.chat_target`; generic file,
    git and terminal work stays on the default orchestrator. Failing closed is
    required because an inherited-key node row has an empty `api_token`, which
    the executor would otherwise read as "run locally on the API host".
    """


# Claude Code is the only backend that accepts a launch effort flag.
SUPPORTED_REASONING_EFFORT_BACKENDS = {"claude_code"}


def _effective_backend(bot_config: BotConfig) -> str:
    return bot_config.backend or bot_config.api_type


# --- Tier helpers ---

def tier_of(bot_config: BotConfig) -> str:
    """Return the strongest tier for display and legacy readers."""
    return tiers_of(bot_config)[0]


def served_tier(bot_config: BotConfig, bot_tier: str = None, auth_mode: str = "relay") -> str:
    """Record the requested tier if served, then the default, then strongest."""
    tiers = list(subscription_tiers_of(bot_config) or {}) if auth_mode == "subscription" else tiers_of(bot_config)
    if not tiers:
        tiers = tiers_of(bot_config)
    return next((tier for tier in (bot_tier, "tier2") if tier in tiers), tiers[0])


class BotAuthModeError(ValueError):
    """The node's auth mode cannot serve the requested bot or pool."""


def bot_supports_auth_mode(config: BotConfig, auth_mode: str = "relay") -> bool:
    if auth_mode in (None, "", "relay"):
        return True
    return auth_mode == "subscription" and bool(subscription_tiers_of(config))


def _pool_weight(config: BotConfig, tier: str = None, auth_mode: str = "relay") -> Optional[float]:
    if auth_mode == "subscription":
        tiers = subscription_tiers_of(config) or {}
        return tiers.get(tier or served_tier(config, auth_mode=auth_mode))
    return tier_weight(config, tier) if tier else config.route_weight


def _pool_candidate_viable(config: BotConfig, pool_size: int, tier: str = None,
                           auth_mode: str = "relay") -> bool:
    weight = _pool_weight(config, tier, auth_mode)
    return (weight is None and pool_size == 1) or (weight is not None and weight > 0)


def bot_tier_pools(configs: List[BotConfig], auth_mode: str = "relay") -> dict[str, List[str]]:
    """Return viable draw members without reading or changing routing state."""
    universe = [cfg for cfg in configs if cfg.enabled and not cfg.ref_bot_name]
    pools = {}
    for tier in TIERS:
        candidates = _candidates(universe, tier=tier, auth_mode=auth_mode)
        candidates = [cfg for cfg in candidates
                      if _pool_candidate_viable(cfg, len(candidates), tier, auth_mode)]
        pools[tier] = sorted(cfg.name for cfg in candidates)
    return pools


def _deref_bot_config(user_id: int, bot_config: BotConfig, visited: Optional[set] = None, depth: int = 0, auth_mode: str = "relay") -> BotConfig:
    """Recursively dereference a ref bot to its target config.

    Relay follows ref_bot_name. Subscription follows sub_ref_bot_name and
    fails closed when that target is missing, disabled, a pointer, or not
    subscription-eligible. Returns the original config when the followed
    name is unset. Raises ValueError on circular refs or max depth exceeded.
    """
    ref_name = bot_config.sub_ref_bot_name if auth_mode == "subscription" else bot_config.ref_bot_name
    if not ref_name:
        return bot_config

    if depth >= _MAX_REF_DEPTH:
        raise ValueError(
            f"Max ref depth ({_MAX_REF_DEPTH}) exceeded resolving bot '{bot_config.name}'"
        )

    visited = visited or set()
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
        if auth_mode == "subscription":
            raise BotAuthModeError(
                f"pointer {bot_config.name!r} subscription ref {ref_name!r} is not a runnable subscription bot"
            )
        raise ValueError(
            f"Ref target bot '{ref_name}' not found (resolving '{bot_config.name}')"
        )
    if auth_mode == "subscription" and (
        not target.enabled or target.ref_bot_name or not bot_supports_auth_mode(target, auth_mode)
    ):
        raise BotAuthModeError(
            f"pointer {bot_config.name!r} subscription ref {ref_name!r} is not a runnable subscription bot"
        )

    return _deref_bot_config(user_id, target, visited, depth + 1, auth_mode)


def _universe(user_id: int) -> List[BotConfig]:
    """Return enabled, non-pointer configs eligible for explicit filters.

    User's own configs, falling back to the system default user's configs
    only when the user has none of their own. Disabled and pointer bots are
    out (an explicit name pin to a disabled bot degrades to tier2, see
    resolve_bot_config). Model-type configs remain here so name and backend
    pins can reach them. Tier candidacy excludes them in _candidates.
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
    ]


def _candidates(universe: List[BotConfig], bot_name: str = None, backend: str = None, tier: str = None, effort: str = None, auth_mode: str = "relay") -> List[BotConfig]:
    """Intersect the universe with the given filters.

    Filters combine with AND, not precedence: bot_name, backend, and tier
    each narrow the pool further when given. The tier filter additionally
    excludes model-type bots (the inline query bots are pin-only, not pool
    members).
    """
    result = [cfg for cfg in universe if bot_supports_auth_mode(cfg, auth_mode)]
    if bot_name:
        result = [cfg for cfg in result if cfg.name == bot_name]
    if backend:
        result = [cfg for cfg in result if _effective_backend(cfg) == backend]
    if tier:
        result = [
            cfg for cfg in result
            if tier in (subscription_tiers_of(cfg) or {} if auth_mode == "subscription" else tiers_of(cfg))
            and (getattr(cfg, "type", None) or "agent") != "model"
        ]
    if effort:
        result = [cfg for cfg in result if effort in effective_effort_levels(cfg)]
    return result


def _pick_by_weight(bots: List[BotConfig], tier: str = None, auth_mode: str = "relay") -> Optional[BotConfig]:
    """Weighted random pick from bots by route_weight.

    Probability = route_weight / sum(route_weights). Bots with
    route_weight <= 0 are excluded from the draw. Only called with 2+
    candidates (see _select); an explicit zero also excludes a sole candidate.
    """
    eligible = [(cfg, weight) for cfg in bots if (weight := _pool_weight(cfg, tier, auth_mode)) and weight > 0]
    if not eligible:
        return None
    choices, raw_weights = zip(*eligible, strict=True)
    total = sum(raw_weights)
    weights = [w / total for w in raw_weights]
    return random.choices(choices, weights=weights, k=1)[0]


def _select(candidates: List[BotConfig], user_id: int = None, tier: str = None, auth_mode: str = "relay") -> Optional[BotConfig]:
    """Pick a config from a candidate pool.

    A sole candidate is used unless its weight is explicitly zero; a
    multi-candidate tier pool uses persisted smooth weighted round-robin;
    other multi-candidate pools draw by weight. Both may come up empty if
    every candidate has zero/unset weight.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0] if _pool_candidate_viable(candidates[0], 1, tier, auth_mode) else None
    if user_id is not None and tier:
        selected_name = bot_service.select_weighted_round_robin(
            user_id,
            tier,
            [(cfg.name, weight) for cfg in candidates if (weight := _pool_weight(cfg, tier, auth_mode)) and weight > 0],
        )
        if selected_name:
            return next(cfg for cfg in candidates if cfg.name == selected_name)
        return None
    return _pick_by_weight(candidates, tier, auth_mode)


def _subscription_pointer(user_id: int, universe: List[BotConfig], pinned: BotConfig) -> BotConfig:
    """Resolve an enabled pointer on a subscription node. Never follows ref_bot_name."""
    if not pinned.sub_ref_bot_name:
        selected = _select(
            _candidates(universe, tier="tier2", auth_mode="subscription"),
            user_id=user_id, tier="tier2", auth_mode="subscription",
        )
        if not selected:
            raise BotAuthModeError(
                f"pointer {pinned.name!r} has no subscription ref and no runnable subscription tier2 bot"
            )
        return selected
    return _deref_bot_config(user_id, pinned, auth_mode="subscription")


def _global_default(user_id: int) -> BotConfig:
    bot_config = bot_service.get_config(user_id)
    if not bot_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            bot_config = bot_service.get_config(default_user_id)
    if not bot_config:
        raise ValueError(f"No bot config found for user_id={user_id}")
    return _deref_bot_config(user_id, bot_config)


def _resolve_filters(user_id: int, universe: List[BotConfig], bot_name: str = None,
                     backend: str = None, tier: str = None, effort: str = None, auth_mode: str = "relay") -> Optional[BotConfig]:
    """Intersect the filters over the universe, without the tier2 fallback."""
    candidates = _candidates(universe, bot_name=bot_name, backend=backend, tier=tier,
                             effort=effort, auth_mode=auth_mode)
    selected = candidates[0] if bot_name and len(candidates) == 1 else _select(
        candidates, user_id=user_id if tier else None, tier=tier, auth_mode=auth_mode,
    )
    if not selected and bot_name and not backend and not tier:
        # Explicit name pins keep pointer-deref semantics even though
        # ref bots are excluded from the universe: name addressing
        # (story 20 aliasing) should still reach the pointer's target.
        pinned = bot_service.get_config(user_id, bot_name)
        if pinned and pinned.ref_bot_name and pinned.enabled:
            if auth_mode == "subscription":
                selected = _subscription_pointer(user_id, universe, pinned)
            else:
                selected = _deref_bot_config(user_id, pinned)
    if bot_name and auth_mode == "subscription":
        pinned = selected or _resolve_filters(user_id, universe, bot_name)
        if pinned is None:
            raise BotAuthModeError(f"bot {bot_name!r} is not a runnable named bot")
        if not bot_supports_auth_mode(pinned, auth_mode):
            raise BotAuthModeError(f"bot {bot_name!r} is not eligible for subscription auth")
    return selected


def _resolve_named(user_id: int, bot_name: str, backend: str = None, tier: str = None) -> Optional[BotConfig]:
    """Resolve one named bot the way resolve_bot_config does, without round-robin.

    A backend or tier filter disables pointer deref. Zero or several matches
    stay unresolved, so effort admission cannot pick a substitute.
    """
    matches = _candidates(_universe(user_id), bot_name=bot_name, backend=backend, tier=tier)
    if len(matches) == 1:
        return matches[0]
    if backend or tier or matches:
        return None
    pinned = bot_service.get_config(user_id, bot_name)
    if pinned and pinned.ref_bot_name and pinned.enabled:
        return _deref_bot_config(user_id, pinned)
    return None


def resolve_pinned_bot_config(user_id: int, bot_name: str, tier: str = None, auth_mode: str = "relay") -> Optional[BotConfig]:
    """Resolve an explicit bot-name pin, or None when the pin does not resolve.

    Same candidate rules as resolve_bot_config for a name pin (pointer deref
    included), minus the tier2 fallback. A caller that must know whether its
    request was actually honored needs "no runnable config by that name"
    (unknown, disabled, or outside the requested tier) to stay distinguishable
    from "the pool handed something back"; resolve_bot_config deliberately
    erases that difference so a dispatch always gets a bot. Raises on a broken
    ref chain, like resolve_bot_config.
    """
    return _resolve_filters(user_id, _universe(user_id), bot_name, tier=tier, auth_mode=auth_mode)


def _require_declared(selected: Optional[BotConfig], effort: str, bot_name: str) -> None:
    """A named bot is checked on its own. Never substitute another bot."""
    if selected is None or effort not in effective_effort_levels(selected):
        raise EffortCapabilityError(effort, bot_name)


def resolve_bot_config(user_id: int, bot_name: str = None, backend: str = None, tier: str = None, effort: str = None, auth_mode: str = "relay") -> BotConfig:
    """Resolve a dispatch request to a bot config.

    Unified filter resolution (no precedence chain): bot_name / backend /
    tier intersect over the user's universe of eligible configs. Exactly
    one match is used directly; multiple tier matches use persisted smooth
    weighted round-robin. No
    filters, or an empty intersection, re-resolves against the tier2 pool;
    an empty tier2 pool falls back to the user's global default bot.

    Explicit effort changes the empty case: a name pin that does not declare
    the level fails instead of switching, and an empty filtered pool fails
    instead of falling through to an unfiltered tier2 or the global default.
    No effort keeps the fallback above.
    """
    universe = _universe(user_id)

    if bot_name or backend or tier:
        # A name pin is resolved first, then checked. Filtering the pool by
        # effort would hide the pin and look like "no such bot".
        selected = _resolve_filters(
            user_id, universe, bot_name, backend, tier,
            effort=None if bot_name else effort, auth_mode=auth_mode,
        )
        if bot_name and effort:
            _require_declared(selected, effort, bot_name)
        if selected:
            return selected
        if effort:
            raise EffortCapabilityError(effort, bot_name)
        logger.warning(
            "No bot matched filters (bot_name=%s backend=%s tier=%s) for user_id=%s; falling back to tier2",
            bot_name, backend, tier, user_id,
        )
    elif effort:
        selected = _select(
            _candidates(universe, tier="tier2", effort=effort, auth_mode=auth_mode),
            user_id=user_id, tier="tier2", auth_mode=auth_mode,
        )
        if not selected:
            raise EffortCapabilityError(effort)
        return selected

    tier2 = _select(_candidates(universe, tier="tier2", auth_mode=auth_mode),
                    user_id=user_id, tier="tier2", auth_mode=auth_mode)
    if tier2:
        return tier2

    if auth_mode not in (None, "", "relay"):
        raise BotAuthModeError(f"no runnable bot in {auth_mode!r} tier2 pool")

    logger.warning("Empty tier2 pool for user_id=%s; falling back to default bot", user_id)
    return _global_default(user_id)


def preflight_launch_effort(user_id: int, effort: str = None, *, chat=None, bot_name: str = None, bot_tier: str = None, backend: str = None) -> None:
    """Refuse an explicit effort this launch cannot run, without routing writes.

    Same decision as the worker gate: a re-bot target, a sticky or pinned bot,
    or the filtered pool. None returns before any bot read. A pool is admissible
    only when the filtered candidates have a viable weight: positive, or unset
    for a sole candidate. An explicit zero is never an automatic draw. Never calls select_weighted_round_robin.
    """
    if effort is None:
        return

    def reject_undeclared(selected: Optional[BotConfig], name: str) -> None:
        if selected is not None and effort in effective_effort_levels(selected):
            return
        if selected is None:
            raise EffortCapabilityError(effort, name)
        raise EffortCapabilityError(effort, selected.name, declared=effective_effort_levels(selected))

    def reject_unsupported(selected: BotConfig) -> None:
        unsupported = _effective_backend(selected)
        if unsupported not in SUPPORTED_REASONING_EFFORT_BACKENDS:
            raise ValueError(f"reasoning_effort is only supported for claude_code, not {unsupported}")

    chat_bot = getattr(chat, "bot_name", None) if chat is not None else None
    chat_backend = getattr(chat, "backend", None) if chat is not None else None
    if chat_bot and bot_name and bot_name != chat_bot:
        target = resolve_pinned_bot_config(user_id, bot_name, tier=bot_tier)
        reject_undeclared(target, bot_name)
        target_backend = _effective_backend(target)
        if chat_backend and target_backend != chat_backend:
            own = _resolve_named(user_id, chat_bot, backend=chat_backend or backend, tier=bot_tier)
            reject_undeclared(own, chat_bot)
            reject_unsupported(own)
            return
        reject_unsupported(target)
        return

    pin = chat_bot or bot_name
    if pin:
        selected = _resolve_named(user_id, pin, backend=chat_backend or backend, tier=bot_tier)
        reject_undeclared(selected, pin)
        reject_unsupported(selected)
        return

    pool_backend = chat_backend or backend
    pool_tier = bot_tier if (bot_tier or pool_backend) else "tier2"
    candidates = _candidates(_universe(user_id), backend=pool_backend, tier=pool_tier, effort=effort)
    viable = any(_pool_candidate_viable(cfg, len(candidates), pool_tier) for cfg in candidates)
    if not viable:
        raise EffortCapabilityError(effort)


def resolve_vm_config(user_id: int, vm_name: str = None, work_dir: str = None) -> VmConfig:
    """Resolve the generic default VM for non-chat work (files, terminal, images).

    Chat execution does not use this: a chat resolves its node strictly from
    ``vm_config`` and never lets a work-dir match substitute another machine.
    Generic work is default-only. Naming a non-default node raises instead of
    falling back, because a chat-only node row may inherit its SSH key (empty
    ``api_token``) and the executor would treat that as local execution on the
    API host. Here the work-dir auto-match is likewise limited to the default
    row.
    """
    canonical = vm_service.normalize_node_name(vm_name)
    if canonical != vm_service.DEFAULT_NODE:
        raise VmConfigError(
            f"generic VM commands run on the default node only; node {canonical!r} is chat-only"
        )
    vm_config = vm_service.get_config(user_id, canonical)
    if not vm_config and work_dir:
        candidate = vm_service.get_config_by_work_dir(user_id, work_dir)
        if candidate is not None and candidate.name == "default":
            vm_config = candidate
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
