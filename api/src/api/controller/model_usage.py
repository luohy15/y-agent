import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request

from storage.service import model_usage_daily as usage_service
from storage.service import model_usage_limits as limits_service
from storage.service.model_usage_daily import _local_today
from storage.service.time_range import parse_time_range

router = APIRouter(prefix="/usage")

# Internal-only fields stripped before returning rows to the API layer
# (per the ID convention: never expose integer id / user_id).
_INTERNAL_FIELDS = ("id", "user_id")


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


@router.get("/limits")
async def limits(request: Request):
    """Live subscription limit-window status (Claude + Codex, 5h and 1w) for
    every provider account bound to the user's CRS relay keys. Independent of
    the daily spend sync: no persistence, always a fresh read (subject to
    CRS's own cache TTL), and manual retry / automatic poll both call this
    same safe read endpoint."""
    user_id = request.state.user_id
    status = await limits_service.get_limit_status(user_id)
    return {
        **status,
        "timezone": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
    }
