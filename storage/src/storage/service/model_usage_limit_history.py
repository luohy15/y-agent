"""Durable subscription limit-window history (todo 3717).

Every refresh that actually runs leaves an attempt row. A successful
attempt also leaves one observation per reported window, plus a
provider-level row when a provider reports an error, reports no windows,
or is one of the three expected backends and is simply absent. Nothing is
zero-filled and nothing is taken from the merged snapshot fallback: only
the incoming normalized envelope is recorded.

Freshness describes the source against the attempt stamp, at read time,
and is never stored. It is not "how fresh is this row right now".
`attempted_at` is the attempt's start. A source time up to
ATTEMPT_WINDOW_SECONDS after that stamp is labelled as inside the
allowance, not as proof the attempt was still running. A null or
unparseable source time is `unknown`; a source time past the allowance is
`future`; only an `available` row can be `fresh` or `stale`. A slow manual
retry reads `future`, never falsely `fresh`.

Reset identity is the exact reset_at value. A null reset is its own group
and is never merged with a known reset or inferred from the window length.
"""

import os
from datetime import date, datetime, time, timedelta, timezone

from storage.repository import model_usage_limit_history as repo
from storage.service import model_usage_hourly as hourly_service
from storage.service.model_usage_limits import (
    DEFAULT_TTL_SECONDS,
    _remaining_percent,
    _valid_percent,
)
from storage.util import _time_filter_tz

# The three backends a successful envelope is expected to cover. An absent
# one is recorded as missing rather than dropped.
EXPECTED_BACKENDS = ("claude_code", "codex", "grok")

# errors[].origin -> the backend that error belongs to. An unmatched origin
# leaves the missing row's error NULL.
_ERROR_ORIGIN_BACKEND = {
    "claude_tui_usage": "claude_code",
    "codex_usage_api": "codex",
    "xai_billing_credits": "grok",
}

_WINDOW_KINDS = ("five_hour", "one_week", "billing_period")

# Spend-provider names as model_usage_hourly stores them, keyed by the
# limit-window provider name.
_USAGE_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "xai": "x-ai",
}

MAX_RANGE_DAYS = 31
# ~4x a full 31-day observation set. Above this the read refuses instead of
# truncating. Attempts are capped on the same multiple so a run of failures
# (which write no observations) cannot return an unbounded payload either.
MAX_OBSERVATIONS = 60_000
MAX_ATTEMPTS = 60_000

RANGE_TOO_LARGE = "range_too_large"


class RangeTooLarge(ValueError):
    """The requested window is wider than 31 days or holds more rows than the cap."""

    def __init__(self):
        super().__init__(RANGE_TOO_LARGE)


def _parse_utc(value) -> datetime | None:
    """Parse an ISO timestamp into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_bucket(attempted_at: datetime) -> tuple[date, int]:
    local = attempted_at.astimezone(_time_filter_tz())
    return local.date(), local.hour


# Allowance, not a measured completion and not a bound on a manual retry.
# The sweep abandons a user at 45s, so a scheduled row exists only inside
# that cap. The manual path has no whole-attempt cap: the VM lookup, the EC2
# probe, and the SSH connect run outside the 30s CLI timeout. 60s sits above
# those two numbers. A source time past it is future, which is the
# conservative result for a slow manual attempt. Not imported from the worker.
ATTEMPT_WINDOW_SECONDS = 60


def _freshness(state: str, observed_at: datetime | None, attempted_at: datetime) -> str:
    """Source freshness against the attempt, not current freshness.

    Non-available states are `unavailable` even when a source time exists.
    A missing or unparseable source time is `unknown`. A source time past
    the allowance is `future` and is never called fresh. That label is
    conservative: a slow manual attempt does not read as fresh.
    """
    if state != "available":
        return "unavailable"
    if observed_at is None:
        return "unknown"
    if observed_at > attempted_at + timedelta(seconds=ATTEMPT_WINDOW_SECONDS):
        return "future"
    age = max(0.0, (attempted_at - observed_at).total_seconds())
    if age <= DEFAULT_TTL_SECONDS:
        return "fresh"
    return "stale"


def _state_of(item: dict) -> str:
    raw = item.get("availability") or "unavailable"
    if raw in ("available", "unavailable", "reauth_required"):
        return raw
    return "unavailable"


def _account_key(item: dict) -> str:
    account_id = item.get("account_id")
    if isinstance(account_id, str) and account_id:
        return account_id
    return ""


def _error_for_backend(errors, backend: str) -> str | None:
    for entry in errors or []:
        if not isinstance(entry, dict):
            continue
        if _ERROR_ORIGIN_BACKEND.get(entry.get("origin")) == backend and entry.get("error"):
            return entry.get("error")
    return None


def _window_rows(item: dict) -> list[tuple[str, dict | None]]:
    """(window_key, raw window or None) for every window worth a row.

    A window whose used_percent does not survive _valid_percent is still a
    row: the percent is stored NULL, the window is not dropped.
    """
    windows = item.get("windows") or {}
    rows = []
    for kind in _WINDOW_KINDS:
        raw = windows.get(kind)
        if isinstance(raw, dict):
            rows.append((kind, raw))
    extra = item.get("extra_windows") or {}
    if isinstance(extra, dict):
        for key in sorted(extra):
            raw = extra.get(key)
            if isinstance(raw, dict):
                rows.append((f"extra:{key}", raw))
    return rows


def _account_signals(item: dict) -> tuple[str | None, bool | None]:
    """plan and limit_reached are account-wide. Absent or wrong-typed values
    stay NULL; a bool is the only accepted limit_reached."""
    plan = item.get("plan")
    if not isinstance(plan, str) or not plan:
        plan = None
    reached = item.get("limit_reached")
    if not isinstance(reached, bool):
        reached = None
    return plan, reached


def build_rows(user_id: int, attempt_id: str, attempted_at: str, trigger: str,
               status: str, error: str | None, envelope: dict | None) -> tuple[dict, list[dict]]:
    """Pure: one attempt dict plus its observation dicts. No I/O.

    A failed attempt (or a success handed no envelope) yields no observations.
    """
    collected = _parse_utc(attempted_at)
    if collected is None:
        raise ValueError(f"unparseable attempted_at: {attempted_at!r}")
    attempt_date, attempt_hour = _local_bucket(collected)
    attempt = {
        "attempt_id": attempt_id,
        "user_id": user_id,
        "attempted_at": attempted_at,
        "attempt_date": attempt_date,
        "attempt_hour": attempt_hour,
        "trigger": trigger,
        "status": status,
        "error": error,
    }
    if status != "ok" or not isinstance(envelope, dict):
        return attempt, []

    providers = [p for p in (envelope.get("providers") or []) if isinstance(p, dict)]
    errors = envelope.get("errors") or []
    observations: list[dict] = []
    seen_backends = set()

    for item in providers:
        backend = item.get("backend") or ""
        seen_backends.add(backend)
        state = _state_of(item)
        plan, limit_reached = _account_signals(item)
        base = {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "attempt_date": attempt_date,
            "backend": backend,
            "provider": item.get("provider") or "",
            "source": item.get("source") or "",
            "account_key": _account_key(item),
            "account_name": item.get("account_name"),
            "state": state,
            "error": item.get("error"),
            "observed_at": _parse_utc(item.get("observed_at")),
            "plan": plan,
            "limit_reached": limit_reached,
        }
        windows = _window_rows(item)
        if not windows:
            observations.append({**base, "window_key": "", "used_percent": None, "reset_at": None, "extra": None})
            continue
        for window_key, raw in windows:
            extra = raw.get("extra") if isinstance(raw.get("extra"), (dict, list)) else None
            observations.append({
                **base,
                "window_key": window_key,
                "used_percent": _valid_percent(raw.get("used_percent")),
                "reset_at": _parse_utc(raw.get("reset_at")),
                "extra": extra,
            })

    for backend in EXPECTED_BACKENDS:
        if backend in seen_backends:
            continue
        observations.append({
            "attempt_id": attempt_id,
            "user_id": user_id,
            "attempt_date": attempt_date,
            "backend": backend,
            "provider": "",
            "source": "",
            "account_key": "",
            "account_name": None,
            "state": "missing",
            "error": _error_for_backend(errors, backend),
            "observed_at": None,
            "window_key": "",
            "used_percent": None,
            "reset_at": None,
            "plan": None,
            "limit_reached": None,
            "extra": None,
        })
    return attempt, observations


def record_attempt(user_id: int, attempt_id: str, attempted_at: str, trigger: str,
                   status: str, error: str | None = None, envelope: dict | None = None) -> bool:
    """Persist one attempt. Returns False when attempt_id was already stored."""
    attempt, observations = build_rows(
        user_id, attempt_id, attempted_at, trigger, status, error, envelope,
    )
    return repo.insert_attempt(attempt, observations)


def _parse_range(from_date: str, to_date: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid limit history date range") from exc
    if end < start:
        raise ValueError("to_date must be on or after from_date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise RangeTooLarge()
    return start, end


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _attempted_at_dt(attempt) -> datetime:
    parsed = _parse_utc(attempt.attempted_at)
    if parsed is None:
        # attempt_date/hour are the local wall clock recorded at write time.
        local = datetime.combine(attempt.attempt_date, time(attempt.attempt_hour), _time_filter_tz())
        return local.astimezone(timezone.utc)
    return parsed


def _entry_from(samples_in) -> dict:
    """One (backend, account, window, reset group) entry from its samples.

    Each sample is (observation, attempted_at). The latest collection wins;
    distinct_observations counts distinct source times, so two attempts that
    recorded the same source reading count as one.
    """
    latest_row, latest_at = max(samples_in, key=lambda pair: (pair[1], pair[0].attempt_id))
    distinct = set()
    max_used = None
    for row, _attempted in samples_in:
        distinct.add(row.observed_at)
        if row.used_percent is not None and (max_used is None or row.used_percent > max_used):
            max_used = row.used_percent
    return {
        "backend": latest_row.backend,
        "provider": latest_row.provider,
        "account_key": latest_row.account_key,
        "account_name": latest_row.account_name,
        "window_key": latest_row.window_key,
        "reset_at": _iso(latest_row.reset_at),
        "used_percent": latest_row.used_percent,
        "remaining_percent": _remaining_percent(latest_row.used_percent),
        "observed_at": _iso(latest_row.observed_at),
        "freshness": _freshness(latest_row.state, latest_row.observed_at, latest_at),
        "state": latest_row.state,
        "error": latest_row.error,
        "plan": latest_row.plan,
        "limit_reached": latest_row.limit_reached,
        "extra": latest_row.extra,
        "source": latest_row.source,
        "max_used_percent": max_used,
        "distinct_observations": len(distinct),
        "samples": len(samples_in),
    }


def _hours_in_range(start: date, end: date, now: datetime) -> list[tuple[date, int]]:
    """Every local hour from start 00:00 through the current hour, capped at
    end 23:00. Future hours inside the range are not invented."""
    local_now = now.astimezone(_time_filter_tz())
    hours = []
    day = start
    while day <= end:
        last = 23
        if day == local_now.date():
            last = local_now.hour
        elif day > local_now.date():
            break
        for hour in range(last + 1):
            hours.append((day, hour))
        day += timedelta(days=1)
    return hours


def _usage_for(user_id: int, start: date, end: date) -> list[dict]:
    """Per (date, hour, provider) sums from the spend table.

    The hourly service defaults to LIMIT 1000, which silently drops a wide
    range, so the limit here is the row count plus one and the result is
    checked against that count. cost_basis is preserved: this cost is the
    stored API-equivalent figure, not measured subscription spend.
    """
    count = hourly_service.count_for(
        user_id, source="crs", from_date=start.isoformat(), to_date=end.isoformat(),
    )
    rows = hourly_service.list_for(
        user_id, source="crs", from_date=start.isoformat(), to_date=end.isoformat(),
        limit=count + 1,
    )
    if len(rows) > count:
        raise RangeTooLarge()
    grouped: dict[tuple, dict] = {}
    for row in rows:
        provider = _USAGE_PROVIDER.get(row.provider, row.provider)
        key = (row.usage_date, row.usage_hour, provider)
        bucket = grouped.setdefault(key, {
            "usage_date": row.usage_date,
            "usage_hour": row.usage_hour,
            "provider": provider,
            "all_tokens": 0,
            "requests": 0,
            "cost": 0.0,
            "cost_basis": [],
        })
        bucket["all_tokens"] += row.all_tokens or 0
        bucket["requests"] += row.requests or 0
        bucket["cost"] += row.cost or 0.0
        if row.cost_basis and row.cost_basis not in bucket["cost_basis"]:
            bucket["cost_basis"].append(row.cost_basis)
    out = []
    for bucket in grouped.values():
        bases = bucket.pop("cost_basis")
        bucket["cost_basis"] = bases[0] if len(bases) == 1 else (bases or None)
        out.append(bucket)
    out.sort(key=lambda b: (b["usage_date"], b["usage_hour"], b["provider"]))
    return out


def list_limit_history(user_id: int, from_date: str, to_date: str,
                       backend: str | None = None, now: datetime | None = None) -> dict:
    """Bounded, complete read. Raises ValueError for a bad range and
    RangeTooLarge when the window is too wide or holds too many rows."""
    start, end = _parse_range(from_date, to_date)
    if repo.count_observations(user_id, start, end) > MAX_OBSERVATIONS:
        raise RangeTooLarge()
    if repo.count_attempts(user_id, start, end) > MAX_ATTEMPTS:
        raise RangeTooLarge()

    attempts = repo.list_attempts(user_id, start, end)
    observations = repo.list_observations(user_id, start, end)
    if backend:
        observations = [row for row in observations if row.backend == backend]

    by_attempt: dict[str, list] = {}
    for row in observations:
        by_attempt.setdefault(row.attempt_id, []).append(row)

    hours: dict[tuple, dict] = {}
    for attempt in attempts:
        collected = _attempted_at_dt(attempt)
        key = (attempt.attempt_date.isoformat(), int(attempt.attempt_hour))
        hour = hours.setdefault(key, {
            "date": key[0],
            "hour": key[1],
            "attempts": 0,
            "ok": 0,
            "failed": 0,
            "failed_errors": [],
            "entries": [],
            "_groups": {},
        })
        hour["attempts"] += 1
        if attempt.status == "failed":
            hour["failed"] += 1
            if attempt.error and attempt.error not in hour["failed_errors"]:
                hour["failed_errors"].append(attempt.error)
        else:
            hour["ok"] += 1
        for row in by_attempt.get(attempt.attempt_id, []):
            group_key = (row.backend, row.account_key, row.window_key, _iso(row.reset_at))
            hour["_groups"].setdefault(group_key, []).append((row, collected))

    now = now or datetime.now(timezone.utc)
    out_hours = []
    for day, hour_num in _hours_in_range(start, end, now):
        slot = hours.get((day.isoformat(), hour_num))
        if slot is None:
            out_hours.append({
                "date": day.isoformat(),
                "hour": hour_num,
                "attempts": 0,
                "ok": 0,
                "failed": 0,
                "failed_errors": [],
                "entries": [],
            })
            continue
        entries = [_entry_from(group) for group in slot.pop("_groups").values()]
        entries.sort(key=lambda e: (e["backend"], e["account_key"], e["window_key"], e["reset_at"] or ""))
        slot["entries"] = entries
        out_hours.append(slot)

    return {
        "timezone": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "complete": True,
        "hours": out_hours,
        "usage": _usage_for(user_id, start, end),
    }
