"""Normalization plus the persisted latest snapshot (todo 3226) for live
subscription limit-window status (Claude / Codex 5h + 1w windows, Grok
billing-period window).

Separate operational dataset from `model_usage_daily`: no migration SQL, no
sync, no history table. There *is* now one persisted row per user, though:
the latest normalized snapshot lives in the existing `user_preference` table
under key `usage_limits_latest` (see "persisted snapshot" below), so ordinary
`GET /api/usage/limits` reads (`agent.usage_limits.get_limit_status`,
`refresh=False`) are a plain preference lookup here and never touch the VM.
The live provider read itself still happens in the `y` CLI on the user's VM
and is still SSH'd into from the `agent` package (which needs `agent.config` /
`agent.tool_base`, and `storage` must not depend on `agent`, the reverse of
the existing dependency direction) — but only from
`agent.usage_limits.refresh_and_persist_snapshot`, called by the five-minute
worker sweep and by the explicit `?refresh=true` retry, not from every poll.
This module normalizes the CLI's raw per-provider readings into a stable
contract, computes derived fields (remaining percent, freshness), selects one
best account row per backend for the Usage cards, and owns the persisted
snapshot's read/merge/write functions.
"""

import math
from datetime import datetime, timezone

from loguru import logger

from storage.service import user_preference as user_pref_service

# TTL passed to normalize_envelope for a single live CLI attempt (todo 3226:
# still used at refresh time; no longer used to gate an ordinary read, see
# READ_FRESH_SECONDS).
DEFAULT_TTL_SECONDS = 300

_WINDOW_KINDS = ("five_hour", "one_week", "billing_period")

# --- persisted snapshot (todo 3226) ---------------------------------------
#
# Ordinary `GET /api/usage/limits` reads no longer run the CLI: a five-minute
# worker sweep (agent.usage_limits.refresh_and_persist_snapshot) is the only
# writer, persisting one normalized snapshot per user under this
# user_preference key. Reads only look up that row and recompute freshness
# from each provider's own observed_at, never restamping it and never
# touching VM/SSH/CLI.

SNAPSHOT_PREFERENCE_KEY = "usage_limits_latest"

# Fresh classification window for a *read* of the persisted snapshot. Wider
# than DEFAULT_TTL_SECONDS's 5 minutes so the 5-minute refresh cadence's
# ordinary scheduler jitter never flips a just-refreshed snapshot to stale.
READ_FRESH_SECONDS = 600

# Startup / never-refreshed state: no successful snapshot exists yet.
_SNAPSHOT_UNAVAILABLE = "snapshot_unavailable"

# Per-provider error codes meaning "this attempt's read of that one provider
# failed" (transient transport/parse trouble), as distinct from a durable
# state the provider genuinely reported (e.g. reauth_required, not_logged_in).
# Only the former falls back to the previous successful row; a durable state
# must surface over stale good data rather than being hidden behind it.
# `malformed_item` is deliberately excluded: it is an envelope-level error
# (normalize_envelope.errors[]) for an item too malformed to become a
# provider row at all, so it can never appear as a row's own `error` field
# here.
_READ_FAILURE_CODES = {"parse_failed", "transport_error"}

# The whole closed error vocabulary, in one place, for callers that have to
# validate a code coming back out of a snapshot before putting it somewhere
# bounded (the worker sweep's per-user log line). Anything outside this set is
# not a code this system produces and must be collapsed by the caller rather
# than forwarded. See docs/prd/bot-usage.md "Error vocabulary is a closed set
# of codes".
ERROR_CODES = frozenset({
    # provider-level, produced by the VM CLI
    "not_logged_in", "reauth_required", "parse_failed", "transport_error",
    # transport-level, produced by agent.usage_limits
    "vm_unreachable", "cli_failed", "bad_payload", "no_usage_vm",
    # envelope-level, produced by normalize_envelope
    "malformed_item",
    # snapshot-level, produced here
    _SNAPSHOT_UNAVAILABLE,
})


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


# --- persisted snapshot: read / merge / record (todo 3226) ---------------

def _empty_snapshot() -> dict:
    return {
        "providers": [],
        "errors": [],
        "last_attempt_at": None,
        "last_success_at": None,
        "last_attempt_status": None,
        "last_attempt_error": None,
    }


def merge_providers(old_providers: list, new_providers: list) -> list:
    """Combine a fresh attempt's normalized providers with the previously
    persisted snapshot's providers, one row per backend.

    A backend whose new row failed to read *this attempt* (a transient
    transport/parse code) keeps its previous row, so one bad run does not
    blank a card that still has real percentages; its freshness degrades
    naturally on the next read once it ages past READ_FRESH_SECONDS. Every
    other backend takes the new row — including a durable state like
    `reauth_required` or `not_logged_in`, which must surface over stale good
    data rather than being permanently hidden behind it. A backend absent
    from the new attempt entirely also keeps its previous row.
    """
    old_by_backend = {p.get("backend"): p for p in old_providers}
    merged = []
    seen = set()
    for item in new_providers:
        backend = item.get("backend")
        seen.add(backend)
        old = old_by_backend.get(backend)
        if (
            item.get("error") in _READ_FAILURE_CODES
            and old
            and _has_required_window(old.get("windows") or {})
        ):
            merged.append(old)
        else:
            merged.append(item)
    for backend, old in old_by_backend.items():
        if backend not in seen:
            merged.append(old)
    return merged


def _with_read_freshness(providers: list) -> list:
    """Recompute each row's freshness from its own observed_at at read time
    (never restamped) against READ_FRESH_SECONDS, rather than trusting a
    freshness value frozen at refresh time — the same row read nine minutes
    after a five-minute-old refresh must not still claim `fresh`."""
    return [
        {
            **p,
            "freshness": _freshness(
                p.get("availability") or "unavailable",
                p.get("observed_at"),
                p.get("windows") or {},
                READ_FRESH_SECONDS,
            ),
        }
        for p in providers
    ]


def read_snapshot(user_id: int) -> dict:
    """Ordinary `GET /api/usage/limits` read: one preference lookup plus
    freshness normalization, never VM/SSH/CLI. Returns a bounded
    `snapshot_unavailable` envelope before the first successful refresh."""
    pref = user_pref_service.get_preference(user_id, SNAPSHOT_PREFERENCE_KEY)
    if pref is None or not pref.value:
        snapshot = _empty_snapshot()
        snapshot["errors"] = [{"origin": "snapshot", "error": _SNAPSHOT_UNAVAILABLE}]
        return snapshot

    stored = pref.value
    return {
        "providers": _with_read_freshness(stored.get("providers") or []),
        "errors": stored.get("errors") or [],
        "last_attempt_at": stored.get("last_attempt_at"),
        "last_success_at": stored.get("last_success_at"),
        "last_attempt_status": stored.get("last_attempt_status"),
        "last_attempt_error": stored.get("last_attempt_error"),
    }


def record_refresh_success(user_id: int, envelope: dict, attempt_at: str) -> dict:
    """Persist a structurally valid attempt (a well-formed envelope, even one
    carrying isolated provider-level errors) as the new snapshot, merged with
    whatever was previously stored so one bad provider row in an otherwise
    good run never destroys good data for the others."""
    pref = user_pref_service.get_preference(user_id, SNAPSHOT_PREFERENCE_KEY)
    previous = pref.value if pref and pref.value else {}
    merged_providers = merge_providers(previous.get("providers") or [], envelope.get("providers") or [])
    stored = {
        "providers": merged_providers,
        "errors": envelope.get("errors") or [],
        "last_attempt_at": attempt_at,
        "last_success_at": attempt_at,
        "last_attempt_status": "ok",
        "last_attempt_error": None,
    }
    user_pref_service.upsert_preference(user_id, SNAPSHOT_PREFERENCE_KEY, stored)
    return read_snapshot(user_id)


def record_refresh_failure(user_id: int, error_code: str, attempt_at: str) -> dict:
    """Persist failure metadata for a failed attempt (VM unreachable, SSH,
    CLI, or transport/bad-payload level) without discarding the last
    successful provider data; its freshness degrades naturally on read as it
    ages past READ_FRESH_SECONDS."""
    pref = user_pref_service.get_preference(user_id, SNAPSHOT_PREFERENCE_KEY)
    previous = pref.value if pref and pref.value else {}
    stored = {
        "providers": previous.get("providers") or [],
        "errors": [{"origin": "vm", "error": error_code}],
        "last_attempt_at": attempt_at,
        "last_success_at": previous.get("last_success_at"),
        "last_attempt_status": "failed",
        "last_attempt_error": error_code,
    }
    user_pref_service.upsert_preference(user_id, SNAPSHOT_PREFERENCE_KEY, stored)
    return read_snapshot(user_id)
