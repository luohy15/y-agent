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
    _aggregate_basis,
    _crs_targets,
    _derive_provider,
    _local_today,
    _run_bounded,
    new_http_client,
    resolve_key_basis,
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

def _fetch_crs_key_hourly(client: httpx.Client, origin: str, api_key: str, usage_date: str) -> list[dict]:
    """Per-model hourly items for one CRS key on one local date (raises on error)."""
    resp = client.post(
        f"{origin}/apiStats/api/user-model-stats",
        json={"apiKey": api_key, "period": "hourly", "date": usage_date},
        headers={"Content-Type": "application/json"},
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
    *,
    client: httpx.Client | None = None,
    key_basis: dict[tuple[str, str], str] | None = None,
    targets: list[tuple[str, str]] | None = None,
    fetched: dict[tuple[str, str, str], list[dict]] | None = None,
) -> dict:
    """Pull per-model hourly usage across all distinct CRS keys for each date,
    SUM per (model, hour), and upsert as source='crs' scope='aggregate' rows.

    `client` / `key_basis` / `targets` let `sync()` share one connection-pooled
    client, one already-resolved basis map, and one target enumeration with
    the daily grain of the same call; a standalone caller (tests, the CLI
    `backfill --hourly-days`) that omits them gets an owned client and
    resolves its own basis exactly as before. `fetched` additionally lets
    `sync()` submit this grain's (date, key) reads into one merged bounded
    batch alongside basis and daily reads instead of a separate wave; a
    standalone caller that omits it still fetches (with the same bounded
    concurrency) on its own.
    """
    targets = targets if targets is not None else _crs_targets(user_id)
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

    owns_client = client is None
    client = client or new_http_client()
    try:
        basis_map = key_basis if key_basis is not None else resolve_key_basis(client, targets)

        # Every (date, target) pull is independent; run them with bounded
        # concurrency and check failures in the original nested-loop order
        # below so a failing key aborts deterministically with no
        # partial-grain upsert, same as the prior sequential fail-fast loop.
        pairs = [(usage_date, origin, api_key) for usage_date in date_list for origin, api_key in targets]
        if fetched is None:
            fetch_work = {pair: (lambda p=pair: _fetch_crs_key_hourly(client, p[1], p[2], p[0])) for pair in pairs}
            fetched = _run_bounded(fetch_work)
        for pair in pairs:
            result = fetched[pair]
            if isinstance(result, Exception):
                logger.opt(exception=result).error(
                    "sync_crs_hourly: fetch failed for a key on {}: {}", pair[0], result,
                )
                return {
                    "source": "crs-hourly",
                    "status": "error",
                    "reason": str(result),
                    "rows": 0,
                    "dates": date_list,
                }

        # (model, hour, usage_date) -> summed totals across every distinct key.
        agg: dict[tuple[str, int, str], dict] = {}
        agg_basis: dict[tuple[str, int, str], set] = {}
        for usage_date, origin, api_key in pairs:
            basis = basis_map.get((origin, api_key), "real")
            for item in fetched[(usage_date, origin, api_key)]:
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
    finally:
        if owns_client:
            client.close()

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
