"""API latency capture normalization, rollup, retention, and fixed queries."""

from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from storage.repository import api_latency as repo


HIST_VERSION = 1
HISTOGRAM_EDGES_MS = tuple(round(0.5 * (1.15 ** i), 6) for i in range(90))
SUPPORTED_RANGES = {
    "1h": (timedelta(hours=1), "raw"),
    "6h": (timedelta(hours=6), "raw"),
    "24h": (timedelta(hours=24), "raw"),
    "7d": (timedelta(days=7), "raw"),
    "30d": (timedelta(days=30), "hour"),
    "90d": (timedelta(days=90), "hour"),
    "1y": (timedelta(days=365), "day"),
}
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OTHER"})
STATUS_CLASSES = frozenset({"2xx", "3xx", "4xx", "5xx", "unk"})
COMPLETIONS = frozenset({"normal", "disconnect", "cancelled", "internal_failure"})
ORDERINGS = frozenset({"recent", "slowest"})
MODULE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_ROUTE_LENGTH = 512
RAW_RETENTION = timedelta(days=14)
HOURLY_RETENTION = timedelta(days=90)
DAILY_RETENTION = timedelta(days=366)
RETENTION_BATCH_SIZE = 1000
HOT_WINDOW = timedelta(hours=3)
MAX_DIRTY_HOURS_PER_RUN = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def capture(values: dict) -> None:
    """Validate and persist one event from the authoritative middleware."""
    method = values.get("method")
    status_class = values.get("status_class")
    completion = values.get("completion")
    route = values.get("route")
    module_slug = values.get("module_slug") or ""
    started_at = values.get("started_at")
    allowed_keys = {
        "started_at",
        "duration_ms",
        "method",
        "route",
        "status_class",
        "completion",
        "module_slug",
    }
    if set(values) != allowed_keys:
        raise ValueError("invalid API latency event fields")
    if method not in METHODS:
        raise ValueError("invalid API latency method")
    if status_class not in STATUS_CLASSES:
        raise ValueError("invalid API latency status class")
    if completion not in COMPLETIONS:
        raise ValueError("invalid API latency completion")
    if route != "<unmatched>" and not (
        isinstance(route, str)
        and route.startswith("/")
        and len(route) <= MAX_ROUTE_LENGTH
    ):
        raise ValueError("invalid API latency route")
    if module_slug and not MODULE_SLUG_RE.fullmatch(module_slug):
        raise ValueError("invalid API latency module slug")
    if not isinstance(started_at, datetime):
        raise ValueError("invalid API latency start time")
    duration_ms = float(values.get("duration_ms"))
    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("invalid API latency duration")
    repo.create_event({
        **values,
        "started_at": _as_utc(started_at),
        "duration_ms": duration_ms,
        "module_slug": module_slug,
    })


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _floor(value: datetime, grain: str) -> datetime:
    value = _as_utc(value)
    if grain == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _ceil(value: datetime, grain: str) -> datetime:
    floored = _floor(value, grain)
    if value == floored:
        return floored
    return floored + (timedelta(hours=1) if grain == "hour" else timedelta(days=1))


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat().replace("+00:00", "Z") if value else None


def _histogram(durations: Iterable[float]) -> list[int]:
    counts = [0] * (len(HISTOGRAM_EDGES_MS) + 1)
    for duration in durations:
        index = 0
        while index < len(HISTOGRAM_EDGES_MS) and duration > HISTOGRAM_EDGES_MS[index]:
            index += 1
        counts[index] += 1
    return counts


def _merge_histograms(histograms: Iterable[list[int]]) -> list[int]:
    merged = [0] * (len(HISTOGRAM_EDGES_MS) + 1)
    for histogram in histograms:
        if len(histogram) != len(merged):
            raise ValueError("unsupported API latency histogram shape")
        for index, count in enumerate(histogram):
            merged[index] += int(count)
    return merged


def _exact_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _histogram_percentile(
    histogram: list[int],
    percentile: float,
    *,
    observed_max: float | None = None,
) -> float | None:
    total = sum(histogram)
    if total == 0:
        return None
    target = max(1.0, percentile * total)
    cumulative = 0
    for index, count in enumerate(histogram):
        previous = cumulative
        cumulative += count
        if cumulative >= target:
            lower = 0.0 if index == 0 else HISTOGRAM_EDGES_MS[index - 1]
            if index == len(HISTOGRAM_EDGES_MS):
                upper = max(lower, observed_max or lower)
            else:
                upper = HISTOGRAM_EDGES_MS[index]
            fraction = (target - previous) / count if count else 0.0
            return lower + (upper - lower) * fraction
    return HISTOGRAM_EDGES_MS[-1]


def _is_error(row) -> bool:
    return row.status_class == "5xx" or row.completion == "internal_failure"


def _dimensions(row) -> tuple:
    return (row.method, row.route, row.status_class, row.completion, row.module_slug or "")


def _rollup_raw(rows: list, grain: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(_floor(row.started_at, grain), *_dimensions(row))].append(row)
    result = []
    for key, group in grouped.items():
        bucket, method, route, status, completion, module_slug = key
        durations = [float(row.duration_ms) for row in group]
        result.append({
            "grain": grain,
            "bucket_start": bucket,
            "method": method,
            "route": route,
            "status_class": status,
            "completion": completion,
            "module_slug": module_slug,
            "request_count": len(group),
            "error_count": sum(1 for row in group if _is_error(row)),
            "duration_sum_ms": sum(durations),
            "duration_min_ms": min(durations),
            "duration_max_ms": max(durations),
            "histogram": _histogram(durations),
            "hist_version": HIST_VERSION,
        })
    return result


def _rollup_aggregates(rows: list, grain: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(_floor(row.bucket_start, grain), *_dimensions(row))].append(row)
    result = []
    for key, group in grouped.items():
        bucket, method, route, status, completion, module_slug = key
        if any(row.hist_version != HIST_VERSION for row in group):
            raise ValueError("unsupported API latency histogram version")
        result.append({
            "grain": grain,
            "bucket_start": bucket,
            "method": method,
            "route": route,
            "status_class": status,
            "completion": completion,
            "module_slug": module_slug,
            "request_count": sum(row.request_count for row in group),
            "error_count": sum(row.error_count for row in group),
            "duration_sum_ms": sum(row.duration_sum_ms for row in group),
            "duration_min_ms": min(row.duration_min_ms for row in group),
            "duration_max_ms": max(row.duration_max_ms for row in group),
            "histogram": _merge_histograms(row.histogram for row in group),
            "hist_version": HIST_VERSION,
        })
    return result


def _replace_hourly(start: datetime, end: datetime) -> int:
    rows = _rollup_raw(repo.list_events(start, end), "hour")
    repo.replace_rollup_window("hour", start, end, rows)
    return len(rows)


def _replace_daily(start: datetime, end: datetime) -> int:
    day_start = _floor(start, "day")
    day_end = _ceil(end, "day")
    rows = _rollup_aggregates(repo.list_rollups("hour", day_start, day_end), "day")
    repo.replace_rollup_window("day", day_start, day_end, rows)
    return len(rows)


def _replace_dirty_hours(hours: list[datetime]) -> tuple[int, int]:
    hourly_rows = 0
    dirty_days = set()
    for hour in sorted(set(_floor(value, "hour") for value in hours)):
        hourly_rows += _replace_hourly(hour, hour + timedelta(hours=1))
        dirty_days.add(_floor(hour, "day"))
    daily_rows = sum(_replace_daily(day, day + timedelta(days=1)) for day in dirty_days)
    return hourly_rows, daily_rows


def rollup(now: datetime | None = None) -> dict:
    now = (now or _utc_now()).astimezone(timezone.utc)
    retained_start = _floor(now - RAW_RETENTION, "hour")
    reconciliation_start = _ceil(now - RAW_RETENTION, "hour")
    hot_end = _ceil(now, "hour")
    hot_start = max(retained_start, hot_end - HOT_WINDOW)

    # Reconcile only complete hours whose entire raw source is still retained.
    # The straddling boundary hour remains durable after its raw prefix expires.
    raw_counts = dict(repo.raw_hour_counts(reconciliation_start, hot_start))
    stored_counts = dict(repo.rollup_hour_counts(reconciliation_start, hot_start))
    dirty_hours = sorted(
        hour
        for hour in set(raw_counts) | set(stored_counts)
        if raw_counts.get(hour, 0) != stored_counts.get(hour, 0)
    )
    claimed_dirty = dirty_hours[:MAX_DIRTY_HOURS_PER_RUN]

    hourly_rows = _replace_hourly(hot_start, hot_end)
    daily_rows = _replace_daily(hot_start, hot_end)
    dirty_hourly, dirty_daily = _replace_dirty_hours(claimed_dirty)
    hourly_rows += dirty_hourly
    daily_rows += dirty_daily
    return {
        "hourly_rows": hourly_rows,
        "daily_rows": daily_rows,
        "hot_hours": int((hot_end - hot_start).total_seconds() // 3600),
        "dirty_hours": len(dirty_hours),
        "repaired_hours": len(claimed_dirty),
        "reconciliation_complete": len(dirty_hours) <= len(claimed_dirty),
    }


def enforce_retention(now: datetime | None = None, batch_size: int = RETENTION_BATCH_SIZE) -> dict:
    now = (now or _utc_now()).astimezone(timezone.utc)
    deleted = {"raw": 0, "hour": 0, "day": 0}
    operations = (
        ("raw", lambda: repo.delete_event_batch(now - RAW_RETENTION, batch_size)),
        (
            "hour",
            lambda: repo.delete_rollup_batch(
                "hour", _floor(now - HOURLY_RETENTION, "hour"), batch_size
            ),
        ),
        (
            "day",
            lambda: repo.delete_rollup_batch(
                "day", _floor(now - DAILY_RETENTION, "day"), batch_size
            ),
        ),
    )
    for name, operation in operations:
        while True:
            count = operation()
            deleted[name] += count
            if count < batch_size:
                break
    return deleted


def run_maintenance(now: datetime | None = None) -> dict:
    result = rollup(now)
    result["deleted"] = enforce_retention(now)
    return result


def _validate_range(range_name: str) -> tuple[timedelta, str]:
    try:
        return SUPPORTED_RANGES[range_name]
    except KeyError as err:
        raise ValueError(f"unsupported API latency range: {range_name}") from err


def _validate_filters(
    *,
    method: str | None = None,
    status_class: str | None = None,
    completion: str | None = None,
    module_slug: str | None = None,
) -> dict:
    if method is not None and method not in METHODS:
        raise ValueError("unsupported method filter")
    if status_class is not None and status_class not in STATUS_CLASSES:
        raise ValueError("unsupported status_class filter")
    if completion is not None and completion not in COMPLETIONS:
        raise ValueError("unsupported completion filter")
    if module_slug is not None and module_slug != "" and not MODULE_SLUG_RE.fullmatch(module_slug):
        raise ValueError("unsupported module_slug filter")
    return {
        key: value
        for key, value in {
            "method": method,
            "status_class": status_class,
            "completion": completion,
            "module_slug": module_slug,
        }.items()
        if value is not None
    }


def _matches(row, route: str | None, filters: dict) -> bool:
    if route is not None and row.route != route:
        return False
    return all(getattr(row, key) == value for key, value in filters.items())


def _load_range(range_name: str, now: datetime | None, route: str | None, filters: dict):
    duration, source = _validate_range(range_name)
    end = (now or _utc_now()).astimezone(timezone.utc)
    start = end - duration
    if source == "raw":
        query_start = start
        rows = repo.list_events(query_start, end)
    else:
        # Aggregate ranges are explicitly bucket-aligned. Returned bounds match
        # the complete leading bucket that contributes counts and histograms.
        query_start = _floor(start, source)
        rows = (
            repo.list_daily_source(query_start, end)
            if source == "day"
            else repo.list_rollups(source, query_start, _ceil(end, source))
        )
    return query_start, end, source, [
        row for row in rows if _matches(row, route, filters)
    ]


def _metrics(rows: list, source: str) -> dict:
    if source == "raw":
        durations = [float(row.duration_ms) for row in rows]
        count = len(rows)
        errors = sum(1 for row in rows if _is_error(row))
        percentile = lambda value: _exact_percentile(durations, value)
    else:
        count = sum(row.request_count for row in rows)
        errors = sum(row.error_count for row in rows)
        histogram = _merge_histograms(row.histogram for row in rows)
        observed_max = max((row.duration_max_ms for row in rows), default=None)
        percentile = lambda value: _histogram_percentile(
            histogram, value, observed_max=observed_max
        )
    return {
        "request_count": count,
        "error_count": errors,
        "error_rate": errors / count if count else None,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
    }


def _series(rows: list, source: str) -> list[dict]:
    grouped = defaultdict(list)
    grain = "hour" if source in ("raw", "hour") else "day"
    timestamp_attr = "started_at" if source == "raw" else "bucket_start"
    for row in rows:
        grouped[_floor(getattr(row, timestamp_attr), grain)].append(row)
    return [
        {"bucket_start": _iso(bucket), **_metrics(group, source)}
        for bucket, group in sorted(grouped.items())
    ]


def summary(
    range_name: str = "24h",
    *,
    route: str | None = None,
    method: str | None = None,
    status_class: str | None = None,
    completion: str | None = None,
    module_slug: str | None = None,
    now: datetime | None = None,
) -> dict:
    filters = _validate_filters(
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )
    start, end, source, rows = _load_range(range_name, now, route, filters)
    partial_grain = "hour" if source in ("raw", "hour") else "day"
    return {
        "range": range_name,
        "source": source,
        "approximate_percentiles": source != "raw",
        "timezone": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
        "start": _iso(start),
        "end": _iso(end),
        "partial_bucket_start": _iso(_floor(end, partial_grain)) if source != "raw" else None,
        **_metrics(rows, source),
        "series": _series(rows, source),
    }


def routes(
    range_name: str = "24h",
    *,
    min_samples: int = 20,
    limit: int = 50,
    method: str | None = None,
    status_class: str | None = None,
    completion: str | None = None,
    module_slug: str | None = None,
    now: datetime | None = None,
) -> dict:
    if not 1 <= min_samples <= 10_000:
        raise ValueError("min_samples must be between 1 and 10000")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    filters = _validate_filters(
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )
    _start, _end, source, rows = _load_range(range_name, now, None, filters)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.route].append(row)
    ranked = [{"route": route, **_metrics(group, source)} for route, group in grouped.items()]
    for item in ranked:
        item["meets_min_samples"] = item["request_count"] >= min_samples
    ranked.sort(key=lambda item: (
        not item["meets_min_samples"],
        -(item["p95_ms"] or 0),
        item["route"],
    ))
    return {
        "range": range_name,
        "source": source,
        "approximate_percentiles": source != "raw",
        "min_samples": min_samples,
        "routes": ranked[:limit],
    }


def events(
    range_name: str = "24h",
    *,
    route: str | None = None,
    order: str = "recent",
    limit: int = 100,
    method: str | None = None,
    status_class: str | None = None,
    completion: str | None = None,
    module_slug: str | None = None,
    now: datetime | None = None,
) -> dict:
    duration, source = _validate_range(range_name)
    if source != "raw" or duration > RAW_RETENTION:
        raise ValueError("raw events are unavailable outside the 14-day window")
    if order not in ORDERINGS:
        raise ValueError("unsupported event ordering")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    filters = _validate_filters(
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )
    end = (now or _utc_now()).astimezone(timezone.utc)
    rows = repo.query_events(
        end - duration,
        end,
        route=route,
        filters=filters,
        order=order,
        limit=limit,
    )
    return {
        "range": range_name,
        "source": "raw",
        "order": order,
        "events": [
            {
                "started_at": _iso(row.started_at),
                "duration_ms": row.duration_ms,
                "method": row.method,
                "route": row.route,
                "status_class": row.status_class,
                "completion": row.completion,
                "module_slug": row.module_slug or "",
            }
            for row in rows[:limit]
        ],
    }


def meta() -> dict:
    values = repo.storage_meta()
    candidates = [value for value in (values.pop("event_min"), values.pop("rollup_min")) if value]
    return {
        "collection_start": _iso(min(candidates)) if candidates else None,
        "last_rollup": _iso(values.pop("last_rollup")),
        **values,
        "raw_retention_days": RAW_RETENTION.days,
        "hourly_retention_days": HOURLY_RETENTION.days,
        "daily_retention_days": DAILY_RETENTION.days,
        "hist_version": HIST_VERSION,
    }
