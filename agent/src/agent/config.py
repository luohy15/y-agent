"""Shared configuration helpers for CLI and worker."""

import logging
import random
from typing import List, Optional

from storage.dto.bot import (
    TIERS,
    backend_entries_of,
    effective_effort_levels,
    entry_for,
    entry_names,
    preferred_backend,
    subscription_tiers_of,
    tier_weight,
    tiers_of,
)
from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import vm_config as vm_service

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
    """A generic VM command has no owned default node or names a chat-only node.

    Chat execution resolves nodes through `agent.chat_target`; generic file,
    git and terminal work stays on the default orchestrator. Failing closed is
    required because an inherited-key node row has an empty `api_token`, which
    the executor would otherwise read as "run locally on the API host".
    """


# Agentic backends that accept a launch effort flag. Codex and agy have no `max`.
SUPPORTED_REASONING_EFFORT_BACKENDS = {"claude_code", "codex", "agy"}
NO_MAX_EFFORT_BACKENDS = {"codex": "Codex", "agy": "agy"}


def _effective_backend(bot_config: BotConfig) -> str:
    return preferred_backend(bot_config)


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


class BackendMismatchError(ValueError):
    """A later turn would leave the chat's stored backend.

    Callers must not launch another backend's session or draw the global
    default. The two remedies are a new chat, or a bot that stays on the
    stored backend.
    """

    def __init__(self, chat_id: str = None, chat_backend: str = None,
                 other_backend: str = None, bot_name: str = None,
                 entries: Optional[list] = None):
        self.chat_id = chat_id
        self.chat_backend = chat_backend
        self.other_backend = other_backend
        self.bot_name = bot_name
        self.entries = entries
        chat_label = chat_id or "this chat"
        if entries is not None:
            shown = ", ".join(
                entry["backend"] if isinstance(entry, dict) else str(entry) for entry in entries
            ) or "none"
            who = f"bot {bot_name} " if bot_name else ""
            message = f"{who}has no {chat_backend} connection (backends: {shown})"
        elif other_backend:
            who = f"bot {bot_name} " if bot_name else ""
            message = (
                f"chat {chat_label} is on backend {chat_backend} but {who}"
                f"resolves to {other_backend}. Start a new chat to use {other_backend}, "
                f"or continue with a bot that stays on {chat_backend}."
            )
        else:
            message = (
                f"chat {chat_label} is on backend {chat_backend} and no runnable bot "
                f"remains on that backend. Start a new chat, or add a bot on {chat_backend}."
            )
        super().__init__(message)


class BackendRequestError(ValueError):
    """A new chat asked for a backend the resolved bot cannot run."""

    def __init__(self, requested: str, entries: Optional[list] = None, bot_name: str = None):
        self.requested = requested
        self.entries = entries
        self.bot_name = bot_name
        shown = ", ".join(
            entry["backend"] if isinstance(entry, dict) else str(entry) for entry in (entries or [])
        ) or "none"
        who = f"bot {bot_name} " if bot_name else ""
        super().__init__(f"{who}has no {requested} connection (backends: {shown})")


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

    Only the user's own configs are eligible. Disabled and pointer bots are
    out (an explicit name pin to a disabled bot degrades to tier2, see
    resolve_bot_config). Model-type configs remain here so name and backend
    pins can reach them. Tier candidacy excludes them in _candidates.
    """
    configs = bot_service.list_configs(user_id)
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
    if auth_mode == "subscription":
        if backend and backend != "claude_code":
            return []
        result = [cfg for cfg in result if "claude_code" in entry_names(cfg)]
    elif backend:
        result = [cfg for cfg in result if backend in entry_names(cfg)]
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


def launch_entry(chat_backend: str = None, bot_config: BotConfig = None) -> dict:
    """Connection entry a turn launches. No pin selects entry 0, which is persisted."""
    if not chat_backend:
        return backend_entries_of(bot_config)[0]
    return entry_for(bot_config, chat_backend)


def launch_backend(chat_backend: str = None, bot_config: BotConfig = None) -> str:
    """Backend name of ``launch_entry``. This is the value routing persists."""
    return launch_entry(chat_backend, bot_config)["backend"]


def resolve_requested_backend(bot_config: BotConfig, requested: str, auth_mode: str = "relay") -> str:
    """Pin one explicitly named backend on an already resolved bot. No pool fallback."""
    entries = backend_entries_of(bot_config)
    names = [entry["backend"] for entry in entries]
    name = getattr(bot_config, "name", None)
    if auth_mode == "subscription":
        if requested != "claude_code":
            raise BackendRequestError(requested, [{"backend": "claude_code"}], name)
        if "claude_code" not in names:
            raise BackendRequestError("claude_code", entries, name)
        return "claude_code"
    if requested not in names:
        raise BackendRequestError(requested, entries, name)
    return requested


def select_creation_backend(universe: List[BotConfig], *, bot_name: str = None, tier: str = None,
                            requested: str = None, auth_mode: str = "relay",
                            pinned: BotConfig = None) -> Optional[str]:
    """Backend to store on a new chat, or None when the first run pins the preferred.

    Only an explicitly requested backend is pre-pinned; without one the first
    run resolves the bot (pointer deref included) and pins its preferred entry.
    A named bot is strict: no tier2 substitute. An explicit request must be a
    member of that bot's list, or of a viable tier pool when no bot is named.
    Subscription auth never selects codex.
    """
    if bot_name:
        if pinned is None:
            raise ValueError(f"bot '{bot_name}' is unknown, disabled, or outside the requested tier")
        if requested is None:
            # Still refuse a subscription pin the bot cannot serve.
            if auth_mode == "subscription":
                resolve_requested_backend(pinned, "claude_code", auth_mode)
            return None
        return resolve_requested_backend(pinned, requested, auth_mode)

    pool_tier = tier or "tier2"
    if auth_mode == "subscription":
        if requested not in (None, "claude_code"):
            raise BackendRequestError(requested, [{"backend": "claude_code"}])
        candidates = _candidates(universe, backend="claude_code", tier=pool_tier, auth_mode=auth_mode)
        viable = [cfg for cfg in candidates if _pool_candidate_viable(cfg, len(candidates), pool_tier, auth_mode)]
        if not viable:
            raise BackendRequestError("claude_code", [{"backend": "claude_code"}])
        return None if requested is None else "claude_code"

    if requested is None:
        return None
    candidates = _candidates(universe, backend=requested, tier=pool_tier, auth_mode=auth_mode)
    viable = [cfg for cfg in candidates if _pool_candidate_viable(cfg, len(candidates), pool_tier, auth_mode)]
    if not viable:
        raise BackendRequestError(requested, [requested])
    return requested


def resolve_creation_backend(user_id: int, *, bot_name: str = None, tier: str = None,
                             requested: str = None, auth_mode: str = "relay") -> Optional[str]:
    """Resolve the backend a new chat records. None leaves the pin to the first run."""
    pinned = None
    if bot_name:
        pinned = resolve_pinned_bot_config(user_id, bot_name, tier=tier, auth_mode=auth_mode)
    return select_creation_backend(
        _universe(user_id), bot_name=bot_name, tier=tier, requested=requested,
        auth_mode=auth_mode, pinned=pinned,
    )


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


def select_continuation_bot(universe: List[BotConfig], user_id: int, chat_backend: str = None,
                            bot_name: str = None, tier: str = None, effort: str = None,
                            auth_mode: str = "relay", chat_id: str = None) -> BotConfig:
    """Pick a bot for a later turn without leaving ``chat_backend``.

    A null backend delegates to ``resolve_bot_config`` (today's new-chat
    fallback, including the global default). Otherwise the chat's own bot is
    used when it is still on that backend; a dispatch tier filter is ignored
    because the chat's tier is already fixed. A stored name that resolves to
    nothing (deleted or disabled, so it is absent from the universe) may draw
    the same-backend pool (``tier`` or tier2). A name that resolves to another
    backend raises ``BackendMismatchError`` and is never substituted. This
    function does not read or write the database.
    """
    if not chat_backend:
        return resolve_bot_config(
            user_id, bot_name, tier=tier, effort=effort, auth_mode=auth_mode,
        )
    if auth_mode == "subscription" and chat_backend != "claude_code":
        raise BotAuthModeError(f"subscription auth runs claude_code only, not {chat_backend}")

    if bot_name:
        named = [cfg for cfg in universe if cfg.name == bot_name]
        if named:
            chosen = named[0]
            entries = backend_entries_of(chosen)
            if chat_backend not in [entry["backend"] for entry in entries]:
                raise BackendMismatchError(
                    chat_id=chat_id, chat_backend=chat_backend,
                    other_backend=_effective_backend(chosen), bot_name=chosen.name,
                    entries=entries,
                )
            if not bot_supports_auth_mode(chosen, auth_mode):
                raise BotAuthModeError(
                    f"bot {chosen.name!r} is not eligible for {auth_mode!r} auth"
                )
            if effort and effort not in effective_effort_levels(chosen):
                raise EffortCapabilityError(
                    effort, chosen.name, declared=effective_effort_levels(chosen),
                )
            return chosen

    pool_tier = tier or "tier2"
    candidates = _candidates(
        universe, backend=chat_backend, tier=pool_tier, effort=effort, auth_mode=auth_mode,
    )
    # No user_id: a continuation draw must stay DB-free. Round-robin state is a
    # new-chat concern; a sole viable bot is the usual deleted-bot substitute.
    selected = _select(candidates, tier=pool_tier, auth_mode=auth_mode)
    if selected:
        return selected
    if effort:
        raise EffortCapabilityError(effort, bot_name)
    if auth_mode not in (None, "", "relay"):
        raise BotAuthModeError(
            f"no runnable bot in {auth_mode!r} {pool_tier} pool on backend {chat_backend}"
        )
    raise BackendMismatchError(chat_id=chat_id, chat_backend=chat_backend, bot_name=bot_name)


def resolve_continuation_bot_config(user_id: int, chat_id: str, chat_backend: str = None,
                                    bot_name: str = None, tier: str = None, effort: str = None,
                                    auth_mode: str = "relay") -> BotConfig:
    """Load the user's universe and continue on ``chat_backend``.

    A null backend keeps ``resolve_bot_config``. Never infers a backend from a
    session id, and never calls ``_global_default``.
    """
    if not chat_backend:
        return resolve_bot_config(
            user_id, bot_name, tier=tier, effort=effort, auth_mode=auth_mode,
        )
    return select_continuation_bot(
        _universe(user_id), user_id, chat_backend, bot_name, tier, effort, auth_mode,
        chat_id=chat_id,
    )


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
        launch = launch_backend(chat_backend or backend, selected)
        if launch not in SUPPORTED_REASONING_EFFORT_BACKENDS:
            raise ValueError(f"reasoning_effort is only supported for claude_code, codex, or agy, not {launch}")
        if effort == "max" and launch in NO_MAX_EFFORT_BACKENDS:
            raise ValueError(
                f"{NO_MAX_EFFORT_BACKENDS[launch]} does not support reasoning_effort 'max'; expected low, medium, high, or xhigh"
            )

    chat_bot = getattr(chat, "bot_name", None) if chat is not None else None
    chat_backend = getattr(chat, "backend", None) if chat is not None else None
    if chat_bot and bot_name and bot_name != chat_bot:
        target = resolve_pinned_bot_config(user_id, bot_name, tier=bot_tier)
        reject_undeclared(target, bot_name)
        if chat_backend and chat_backend not in entry_names(target):
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
        raise VmConfigError(f"no execution node configured for user_id={user_id}")
    if work_dir:
        vm_config.work_dir = work_dir
    return vm_config
