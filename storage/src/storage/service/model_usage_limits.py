"""Live subscription limit-window status (Claude / Codex 5h + 1w windows).

Separate operational dataset from `model_usage_daily`: no PostgreSQL table, no
sync, no history. Every read fans out concurrently to the user's distinct CRS
relay keys (the same (origin, api_key) targets the daily spend sync already
enumerates) and asks CRS's API-key-scoped self-service endpoint for the latest
cached provider-account snapshot. CRS owns provider account identity, refresh
cadence, and source-specific window mapping; this module only normalizes the
response into a stable contract, computes derived fields (remaining percent,
freshness), and selects one best account row per backend for the Usage cards.
"""

import asyncio
import math
import os
from datetime import datetime, timezone

import httpx
from loguru import logger

from storage.service.model_usage_daily import _BROWSER_UA
from storage.service.model_usage_daily import _crs_targets as _crs_key_targets

# CRS refreshes its own Claude OAuth cache on a ~1 minute cadence and captures
# Codex windows passively off ordinary traffic; a few-minute default keeps the
# UI from flagging a normal in-between-requests gap as stale.
DEFAULT_TTL_SECONDS = int(os.getenv("LIMIT_STATUS_TTL_SECONDS", "300"))

_FETCH_TIMEOUT_SECONDS = 10.0
_REQUIRED_WINDOW_KINDS = ("five_hour", "one_week")


# --- CRS fetch ----------------------------------------------------------------

async def _fetch_crs_limits(origin: str, api_key: str) -> list[dict]:
    """One CRS key's bound-account limit-status entries (raises on transport,
    HTTP, or CRS-reported failure)."""
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{origin}/apiStats/api/user-limit-status",
            json={"apiKey": api_key},
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        resp.raise_for_status()
    body = resp.json()
    if not body.get("success", True):
        raise RuntimeError(body.get("error") or "CRS limit-status request failed")
    return body.get("data") or []


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
    return {
        "used_percent": used,
        "remaining_percent": _remaining_percent(used),
        "reset_at": raw.get("reset_at"),
    }


def _age_seconds(observed_at: str) -> float | None:
    try:
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _has_required_window(windows: dict) -> bool:
    return any(
        windows.get(kind) is not None and windows[kind].get("used_percent") is not None
        for kind in _REQUIRED_WINDOW_KINDS
    )


def _freshness(availability: str, observed_at: str | None, windows: dict, ttl_seconds: int) -> str:
    """fresh / stale / unavailable, derived from source observed_at, required-
    window presence, and the freshness TTL — never from wall-clock page-load
    time and never assumed from a merely-successful CRS probe."""
    if availability == "unavailable":
        return "unavailable"
    if not observed_at or not _has_required_window(windows):
        return "unavailable"
    age = _age_seconds(observed_at)
    if age is None:
        return "unavailable"
    return "fresh" if age <= ttl_seconds else "stale"


def _normalize_account(item: dict, ttl_seconds: int) -> dict:
    windows_raw = item.get("windows") or {}
    windows = {kind: _normalize_window(windows_raw.get(kind)) for kind in _REQUIRED_WINDOW_KINDS}
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
    """Rank one backend's relay-key candidates without depending on target order.

    A fresh usable snapshot always wins; an older usable snapshot is still more
    useful than an unavailable scope. Stable lexical fields make exact ties
    deterministic when two relay keys report the same observation.
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


# --- orchestration ----------------------------------------------------------

async def get_limit_status(user_id: int, ttl_seconds: int | None = None) -> dict:
    """Every distinct CRS key's bound-account limit status, fetched
    concurrently. One target's failure never blocks the others: it is
    reported in `errors` (keyed by origin) while the rest of the read
    proceeds. Successful rows are collapsed at the product boundary to one
    deterministic best candidate per backend, so alternate relay keys and
    unavailable shared-pool scopes cannot duplicate or shadow the dedicated
    Claude/Codex account cards."""
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    targets = _crs_key_targets(user_id)
    if not targets:
        return {"providers": [], "errors": []}

    results = await asyncio.gather(
        *(_fetch_crs_limits(origin, api_key) for origin, api_key in targets),
        return_exceptions=True,
    )

    candidates: dict[str, dict] = {}
    errors: list[dict] = []
    for (origin, _api_key), result in zip(targets, results):
        if isinstance(result, BaseException):
            logger.warning("get_limit_status: fetch failed for {}: {}", origin, result)
            errors.append({"origin": origin, "error": str(result)})
            continue
        for item in result:
            try:
                account = _normalize_account(item, ttl)
            except Exception as e:
                # One malformed item (non-dict, or a windows/extra_windows
                # shape that isn't the expected dict) must not discard the
                # rest of this origin's valid items or any other origin's
                # results — scope the failure to just this item.
                logger.warning("get_limit_status: malformed item from {}: {}", origin, e)
                errors.append({"origin": origin, "error": f"malformed item: {e}"})
                continue
            backend = account.get("backend") or ""
            current = candidates.get(backend)
            if current is None or _candidate_rank(account, origin) > _candidate_rank(current, current["_origin"]):
                candidates[backend] = {**account, "_origin": origin}

    return {
        "providers": [
            {key: value for key, value in candidates[backend].items() if key != "_origin"}
            for backend in sorted(candidates)
        ],
        "errors": errors,
    }
