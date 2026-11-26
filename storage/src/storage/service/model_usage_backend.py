"""Non-relay backend usage: derive model_usage rows from stored agent turns.

agy never goes through the relay, so its turns are invisible to the CRS pull.
The worker already stores one `chat_request_usage` row per agy turn (backend
`agy`, turn delta counters). This service recomputes `source='agy'`
`scope='aggregate'` rows at both grains from those turns, replacing instead of
incrementing, so a re-run is idempotent (todo 4463).

Honesty rules:
- `provider` stays the vendor derived from the model id (a Gemini model id maps
  to `google`); `source` names the ingestion pipe (`agy`).
- `cost` is 0 with `cost_basis='unknown'`: the Google subscription has no
  per-token price, so no dollar figure is invented.
- `requests` counts turn rows (one `agy -p` turn each); internal vendor calls
  per turn are not observable.
- agy reports no cache-write counter, so `cache_create_tokens` stays 0.
  `all_tokens = input + output + cache_read`, matching the relay's allTokens.
"""

from datetime import datetime, time, timedelta

from storage.repository import chat_request_usage as request_repo
from storage.service import model_usage_daily as daily_service
from storage.service import model_usage_hourly as hourly_service
from storage.service.model_usage_daily import _derive_provider
from storage.util import _time_filter_tz, get_utc_iso8601_timestamp, local_today

COST_BASIS_UNKNOWN = "unknown"

_COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens")


def _parse_aware(value):
    """A stored timestamp as an aware datetime, or None when unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _totals() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_create_tokens": 0,
        "cache_read_tokens": 0,
        "requests": 0,
    }


def _row(source: str, day: str, model: str, totals: dict, **extra) -> dict:
    """One aggregate row. Counters come from `totals`, then cost fields."""
    totals["all_tokens"] = (
        totals["input_tokens"] + totals["output_tokens"] + totals["cache_read_tokens"]
    )
    return {
        "usage_date": day,
        "source": source,
        "provider": _derive_provider(model),
        "model": model,
        "scope": "aggregate",
        "scope_id": "",
        "scope_name": "",
        **totals,
        "cost": 0.0,
        "cost_basis": COST_BASIS_UNKNOWN,
        **extra,
    }


def aggregate_rows(rows: list[dict], tz_name=None, source: str = "agy"):
    """Fold turn rows into daily and hourly aggregates in the local timezone.

    Returns `(daily, hourly)` where `daily` maps `(date, model)` to a daily
    row dict and `hourly` is a list of hourly row dicts, each stamped
    `source=source`. A turn's counters are summed only when present; a NULL
    counter contributes nothing. A row with an unusable timestamp is skipped
    (no bucket can be chosen for it).
    """
    tz = _time_filter_tz(tz_name)
    daily: dict[tuple, dict] = {}
    hourly: dict[tuple, dict] = {}
    for turn in rows:
        when = _parse_aware(turn.get("requested_at"))
        if when is None:
            continue
        local = when.astimezone(tz)
        day = local.date().isoformat()
        model = turn.get("model") or "*"
        for bucket, key in (
            (daily, (day, model)),
            (hourly, (day, local.hour, model)),
        ):
            totals = bucket.setdefault(key, _totals())
            for name in _COUNTERS:
                value = turn.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[name] += value
            totals["requests"] += 1

    daily_rows = {
        key: _row(source, key[0], key[1], totals) for key, totals in daily.items()
    }
    hourly_rows = [
        _row(source, day, model, totals, usage_hour=hour)
        for (day, hour, model), totals in hourly.items()
    ]
    return daily_rows, hourly_rows


def sync_backend(user_id: int, backend: str = "agy", synced_at: str | None = None) -> dict:
    """Recompute this owner's `source=<backend>` rows for yesterday and today.

    Both grains are read from `chat_request_usage` in one local-day window, so
    the result is a full recompute rather than an increment: a re-run leaves
    identical rows. Rows outside the window are untouched (no history backfill).
    """
    synced_at = synced_at or get_utc_iso8601_timestamp()
    tz = _time_filter_tz()
    today = local_today()
    start = datetime.combine(today - timedelta(days=1), time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    turns = request_repo.rows_for_backend(user_id, backend, start, end)
    daily, hourly = aggregate_rows(turns, source=backend)
    daily_service.upsert_daily(user_id, list(daily.values()), synced_at)
    hourly_service.upsert_hourly(user_id, hourly, synced_at)
    return {
        "source": backend,
        "status": "ok",
        "rows": len(daily) + len(hourly),
        "daily_rows": len(daily),
        "hourly_rows": len(hourly),
    }
