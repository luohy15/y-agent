import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request

from agent import usage_limits as limits_service
from storage.service import model_usage_daily as usage_service
from storage.service import model_usage_hourly as hourly_service
from storage.service import usage_rate as rate_service
from storage.service.model_usage_daily import _local_today
from storage.service.time_range import parse_time_range

router = APIRouter(prefix="/usage")

# Internal-only fields stripped before returning rows to the API layer
# (per the ID convention: never expose integer id / user_id).
_INTERNAL_FIELDS = ("id", "user_id")


def _local_now():
    """Current local datetime in Y_AGENT_TIMEZONE (shared with local_today)."""
    from storage.util import _time_filter_tz
    return datetime.now(_time_filter_tz())


@router.get("/model-daily")
async def list_model_daily(
    request: Request,
    source: Optional[str] = Query("crs"),
    time: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(100000),
):
    """Per-model daily usage rows. Defaults to source='crs' and today's date
    (the freshest CRS snapshot) when no range is given. When `time` is given it
    is parsed server-side with the shared finance time grammar (specific dates,
    quarters, ranges, ytd/mtd/etc.); fava's exclusive end boundary is converted
    to the repo's inclusive `<=` semantics via −1 day."""
    user_id = request.state.user_id
    if time is not None:
        # `time` is authoritative; its parsed (possibly None) bounds pass
        # straight through, so `all` / `''` stay unbounded instead of
        # collapsing back to the today-default below.
        start, end = parse_time_range(time)
        from_date = start.isoformat() if start else None
        to_date = (end - timedelta(days=1)).isoformat() if end else None
    else:
        today = _local_today()
        from_date = from_date or today
        to_date = to_date or today
    rows = usage_service.list_for(
        user_id,
        source=source,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    return [
        {k: v for k, v in row.to_dict().items() if k not in _INTERNAL_FIELDS}
        for row in rows
    ]


@router.get("/model-hourly")
async def list_model_hourly(
    request: Request,
    source: Optional[str] = Query("crs"),
    time: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(100000),
):
    """Per-model hourly usage rows. Defaults to source='crs' and today's date
    when no range is given (same raw-grain convention as model-daily). Marks
    `partial: true` on rows whose (usage_date, usage_hour) equals the server's
    current configured-timezone hour; the browser clock never decides this
    (todo 3165)."""
    user_id = request.state.user_id
    if time is not None:
        start, end = parse_time_range(time)
        from_date = start.isoformat() if start else None
        to_date = (end - timedelta(days=1)).isoformat() if end else None
    else:
        today = _local_today()
        from_date = from_date or today
        to_date = to_date or today
    rows = hourly_service.list_for(
        user_id,
        source=source,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    now = _local_now()
    partial_date = now.date().isoformat()
    partial_hour = now.hour
    out = []
    for row in rows:
        d = {k: v for k, v in row.to_dict().items() if k not in _INTERNAL_FIELDS}
        d["partial"] = (
            d.get("usage_date") == partial_date and int(d.get("usage_hour", -1)) == partial_hour
        )
        out.append(d)
    return out


@router.get("/daily-totals")
async def list_daily_totals(
    request: Request,
    source: Optional[str] = Query("crs"),
    year: Optional[int] = Query(None),
):
    """Per-day usage totals (tokens / cost / requests) over the contribution
    heatmap's window, independent of the Live time-range filter. A specific
    4-digit `year` returns that calendar year's daily totals; otherwise the
    rolling month-aligned past 12 months. Used so the heatmap always renders its
    full historical window regardless of the donut/table time selection."""
    user_id = request.state.user_id
    return usage_service.daily_totals(user_id, year=year, source=source)


@router.post("/sync")
async def sync(request: Request, source: Optional[str] = Query("crs")):
    """Trigger the CRS model-usage sync, then return the result envelope.
    Mirrors finance /refresh: pulls fresh per-model daily aggregates so the
    usage view can revalidate after the call completes."""
    user_id = request.state.user_id
    return usage_service.sync(user_id, source=source)


@router.get("/rate")
async def rate(request: Request):
    """Current CRS 5-minute RPM/TPM, read by calling the Relay admin
    dashboard directly with the caller's stored admin credentials. See
    docs/prd/bot-usage.md "Realtime run rate"."""
    return rate_service.read_rate(request.state.user_id)


@router.get("/limits")
async def limits(request: Request, refresh: bool = False):
    """Live subscription limit-window status (Claude, Codex, Grok) read
    directly from each provider via `y usage limits --json` over SSH on the
    user's VM. Independent of the daily spend sync: no persistence, a fresh
    read subject to a per-user poll-cost TTL memo, and manual retry /
    automatic poll both call this same endpoint — pass `?refresh=true` for an
    explicit user-initiated retry, which bypasses that memo (and the CLI's
    own on-VM cache) instead of replaying a stale/failed snapshot."""
    user_id = request.state.user_id
    status = await limits_service.get_limit_status(user_id, refresh=refresh)
    return {
        **status,
        "timezone": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
    }
