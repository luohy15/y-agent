"""Normalization for live subscription limit-window status (Claude / Codex
5h + 1w windows, Grok billing-period window).

Separate operational dataset from `model_usage_daily`: no PostgreSQL table, no
sync, no history. The actual provider read now happens in the `y` CLI on the
user's VM (SSH'd into from `agent.usage_limits.get_limit_status`, which lives
in the `agent` package since it needs `agent.config` / `agent.tool_base` and
`storage` must not depend on `agent`, the reverse of the existing dependency
direction). This module only normalizes the CLI's raw per-provider readings
into a stable contract, computes derived fields (remaining percent,
freshness), and selects one best account row per backend for the Usage cards.
"""

import math
from datetime import datetime, timezone

from loguru import logger

# Provider reads are now direct, on-demand pulls (no upstream cache to
# inherit a cadence from); a few-minute default just keeps the UI from
# flagging a normal in-between-poll gap as stale.
DEFAULT_TTL_SECONDS = 300

_WINDOW_KINDS = ("five_hour", "one_week", "billing_period")


# --- normalization --------------------------------------------------------

def _valid_percent(value) -> float | None:
    """Coerce to a finite float, or None for anything malformed (missing,
    non-numeric, NaN, +/-Infinity) — malformed input must never masquerade as
    a real 0-100 percent."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _remaining_percent(used_percent: float | None) -> float | None:
    """100 - used, clamped to [0, 100]; None in means None out."""
    if used_percent is None:
        return None
    return max(0.0, min(100.0, 100.0 - used_percent))


def _normalize_window(raw: dict | None) -> dict | None:
    if not raw:
        return None
    used = _valid_percent(raw.get("used_percent"))
    window = {
        "used_percent": used,
        "remaining_percent": _remaining_percent(used),
        "reset_at": raw.get("reset_at"),
    }
    if "extra" in raw:
        window["extra"] = raw["extra"]
    return window


def _age_seconds(observed_at: str) -> float | None:
    try:
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _has_required_window(windows: dict) -> bool:
    """True if any window kind carries a real percentage — not just
    five_hour/one_week, so a Grok-only billing_period row is usable rather
    than permanently `unavailable`."""
    return any(
        window is not None and window.get("used_percent") is not None
        for window in windows.values()
    )


def _freshness(availability: str, observed_at: str | None, windows: dict, ttl_seconds: int) -> str:
    """fresh / stale / unavailable, derived from source observed_at, required-
    window presence, and the freshness TTL — never from wall-clock page-load
    time and never assumed from a merely-successful provider read. Any
    non-"available" availability (unavailable, reauth_required, ...) is
    unavailable freshness."""
    if availability != "available":
        return "unavailable"
    if not observed_at or not _has_required_window(windows):
        return "unavailable"
    age = _age_seconds(observed_at)
    if age is None:
        return "unavailable"
    return "fresh" if age <= ttl_seconds else "stale"


def _normalize_account(item: dict, ttl_seconds: int) -> dict:
    windows_raw = item.get("windows") or {}
    windows = {kind: _normalize_window(windows_raw.get(kind)) for kind in _WINDOW_KINDS}
    extra_raw = item.get("extra_windows") or {}
    extra_windows = {k: _normalize_window(v) for k, v in extra_raw.items()}
    observed_at = item.get("observed_at")
    availability = item.get("availability") or "unavailable"
    return {
        "backend": item.get("backend"),
        "provider": item.get("provider"),
        "account_id": item.get("account_id"),
        "account_name": item.get("account_name"),
        "observed_at": observed_at,
        "source": item.get("source"),
        "availability": availability,
        "freshness": _freshness(availability, observed_at, windows, ttl_seconds),
        "error": item.get("error"),
        "windows": windows,
        "extra_windows": extra_windows,
    }


def _observed_timestamp(observed_at: str | None) -> float:
    """A deterministic observation-recency value for candidate selection."""
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return float("-inf")
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.timestamp()


def _candidate_rank(account: dict, origin: str) -> tuple:
    """Rank one backend's candidates without depending on read order.

    A fresh usable snapshot always wins; an older usable snapshot is still
    more useful than an unavailable one. Stable lexical fields make exact
    ties deterministic when two candidates report the same observation.
    """
    freshness_rank = {"fresh": 2, "stale": 1, "unavailable": 0}.get(
        account.get("freshness"), 0
    )
    return (
        freshness_rank,
        _has_required_window(account.get("windows") or {}),
        account.get("availability") == "available",
        _observed_timestamp(account.get("observed_at")),
        tuple(
            tuple(-ord(character) for character in str(value or ""))
            for value in (
                account.get("account_id"),
                account.get("account_name"),
                account.get("provider"),
                account.get("source"),
                origin,
            )
        ),
    )


def normalize_envelope(raw: dict, ttl_seconds: int | None = None, origin: str = "vm") -> dict:
    """Normalize + rank a raw `{"providers": [...], "errors": [...]}` payload
    (the shape `y usage limits --json` emits) into the API envelope. One
    malformed item is isolated into `errors` without discarding the rest.

    A well-formed-JSON-but-wrong-shape payload (missing the `providers` key
    entirely, e.g. a producer emitting `{"error": "not logged in"}` on a bad
    login, or not even a dict) is distinct from a genuinely empty envelope:
    it must surface as a partial-read error, not silently collapse into
    `{"providers": [], "errors": []}` — which the UI cannot tell apart from
    "no subscription accounts configured".

    `origin` identifies the transport this payload came over (the caller's
    concept, e.g. "vm" for the CLI-over-SSH path); storage has no opinion on
    it beyond echoing it into candidate tie-breaks and error entries."""
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not isinstance(raw, dict) or "providers" not in raw:
        return {"providers": [], "errors": [{"origin": origin, "error": "bad_payload"}]}

    raw_providers = raw.get("providers") or []
    errors: list[dict] = list(raw.get("errors") or [])

    candidates: dict[str, dict] = {}
    for item in raw_providers:
        try:
            account = _normalize_account(item, ttl)
        except Exception as e:
            logger.warning("normalize_envelope: malformed item from CLI: {}", e)
            errors.append({"origin": origin, "error": "malformed_item"})
            continue
        backend = account.get("backend") or ""
        current = candidates.get(backend)
        if current is None or _candidate_rank(account, origin) > _candidate_rank(current, origin):
            candidates[backend] = account

    return {
        "providers": [candidates[backend] for backend in sorted(candidates)],
        "errors": errors,
    }
