"""Provider-generic hourly LLM usage: per-source pulls into model_usage_hourly.

CRS already records per-key per-model hourly counters (7-day TTL). The go-forward
path reuses the same key enumeration / basis detection as the daily service and
calls POST {origin}/apiStats/api/user-model-stats with period='hourly' + date,
then sums per (model, hour) into one global aggregate row per hour (todo 3165).
"""

from datetime import date, timedelta

import httpx
from loguru import logger

from storage.repository import model_usage_hourly as repo
from storage.service.model_usage_daily import (
    _BROWSER_UA,
    _aggregate_basis,
    _crs_key_basis,
    _crs_targets,
    _derive_provider,
    _local_today,
)
from storage.util import get_utc_iso8601_timestamp, local_today

# CRS keeps hourly counters for ~7 days; wider requests are unrecoverable.
HOURLY_RETENTION_DAYS = 7


# --- thin storage passthroughs ---------------------------------------------

def upsert_hourly(user_id: int, rows: list[dict], synced_at: str | None = None) -> int:
    return repo.upsert_hourly(user_id, rows, synced_at or get_utc_iso8601_timestamp())


def list_for(
    user_id: int,
    source: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 1000,
):
    return repo.list_for(user_id, source=source, from_date=from_date, to_date=to_date, limit=limit)


# --- date window helpers ----------------------------------------------------

def hourly_date_list(days: int, *, include_today: bool = True) -> list[str]:
    """Build a local-date list capped at the CRS hourly TTL (7 days).

    With include_today=True (backfill / default window) the list is the last
    `days` calendar days ending today. With include_today=False it ends at
    yesterday (unused today; kept for symmetry with the daily backfill cap).
    """
    n = max(0, min(int(days), HOURLY_RETENTION_DAYS))
    if n == 0:
        return []
    end = local_today() if include_today else (local_today() - timedelta(days=1))
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def default_hourly_dates() -> list[str]:
    """Go-forward window: yesterday + today (repairs the previous day's final
    hour after midnight; upserts make the re-pull free)."""
    today = date.fromisoformat(_local_today())
    return [(today - timedelta(days=1)).isoformat(), today.isoformat()]


# --- CRS pull ---------------------------------------------------------------

def _fetch_crs_key_hourly(origin: str, api_key: str, usage_date: str) -> list[dict]:
    """Per-model hourly items for one CRS key on one local date (raises on error)."""
    resp = httpx.post(
        f"{origin}/apiStats/api/user-model-stats",
        json={"apiKey": api_key, "period": "hourly", "date": usage_date},
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data") or []


def _item_hour(item: dict) -> int | None:
    """Extract hour 0-23 from a CRS hourly item (accepts hour / usageHour)."""
    raw = item.get("hour")
    if raw is None:
        raw = item.get("usageHour")
    if raw is None:
        return None
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= hour <= 23:
        return hour
    return None


def _item_usage_date(item: dict, fallback: str) -> str:
    return item.get("usageDate") or item.get("usage_date") or fallback


def sync_crs_hourly(
    user_id: int,
    dates: list[str] | None = None,
    synced_at: str | None = None,
) -> dict:
    """Pull per-model hourly usage across all distinct CRS keys for each date,
    SUM per (model, hour), and upsert as source='crs' scope='aggregate' rows."""
    targets = _crs_targets(user_id)
    if not targets:
        return {
            "source": "crs-hourly",
            "status": "skip",
            "reason": "no cr_ keys in bot_configs",
            "rows": 0,
        }

    date_list = list(dates) if dates is not None else default_hourly_dates()
    if not date_list:
        return {"source": "crs-hourly", "status": "ok", "rows": 0, "dates": []}

    # (model, hour, usage_date) -> summed totals across every distinct key.
    agg: dict[tuple[str, int, str], dict] = {}
    agg_basis: dict[tuple[str, int, str], set] = {}
    # Resolve cost basis once per key for the whole multi-date run.
    key_basis = {(origin, api_key): _crs_key_basis(origin, api_key) for origin, api_key in targets}

    for usage_date in date_list:
        for origin, api_key in targets:
            basis = key_basis[(origin, api_key)]
            try:
                items = _fetch_crs_key_hourly(origin, api_key, usage_date)
            except Exception as e:
                logger.exception(
                    "sync_crs_hourly: fetch failed for a key on {}: {}", usage_date, e,
                )
                return {
                    "source": "crs-hourly",
                    "status": "error",
                    "reason": str(e),
                    "rows": 0,
                    "dates": date_list,
                }
            for item in items:
                hour = _item_hour(item)
                if hour is None:
                    continue
                model = item.get("model") or "*"
                day = _item_usage_date(item, usage_date)
                key = (model, hour, day)
                costs = item.get("costs") or {}
                agg_basis.setdefault(key, set()).add(basis)
                row = agg.setdefault(key, {
                    "input_tokens": 0, "output_tokens": 0, "cache_create_tokens": 0,
                    "cache_read_tokens": 0, "all_tokens": 0, "requests": 0, "cost": 0.0,
                })
                row["input_tokens"] += item.get("inputTokens") or 0
                row["output_tokens"] += item.get("outputTokens") or 0
                row["cache_create_tokens"] += item.get("cacheCreateTokens") or 0
                row["cache_read_tokens"] += item.get("cacheReadTokens") or 0
                row["all_tokens"] += item.get("allTokens") or 0
                row["requests"] += item.get("requests") or 0
                row["cost"] += costs.get("real", costs.get("total", 0.0)) or 0.0

    rows = [{
        "usage_date": day,
        "usage_hour": hour,
        "source": "crs",
        "provider": _derive_provider(model),
        "model": model,
        "scope": "aggregate",
        "scope_id": "",
        "scope_name": "",
        "cost_basis": _aggregate_basis(agg_basis[(model, hour, day)]),
        **totals,
    } for (model, hour, day), totals in agg.items()]

    n = upsert_hourly(user_id, rows, synced_at)
    logger.info(
        "sync_crs_hourly: {} keys x {} dates -> upserted {} aggregate rows",
        len(targets), len(date_list), n,
    )
    return {
        "source": "crs-hourly",
        "status": "ok",
        "rows": n,
        "dates": date_list,
    }


def backfill_crs_hourly(
    user_id: int,
    days: int = HOURLY_RETENTION_DAYS,
    synced_at: str | None = None,
) -> dict:
    """Replay the per-key hourly path for the recoverable window (≤7 days).

    Unlike the daily admin backfill, hourly history is only on the per-key
    counters (same endpoint as go-forward), so this reuses sync_crs_hourly.
    Caps at HOURLY_RETENTION_DAYS regardless of the requested depth.
    """
    dates = hourly_date_list(days, include_today=True)
    result = sync_crs_hourly(user_id, dates=dates, synced_at=synced_at)
    result["hourly_days"] = len(dates)
    result["requested_days"] = days
    return result
