from typing import Optional

from fastapi import APIRouter, Query, Request

from storage.service import model_usage_daily as usage_service
from storage.service.model_usage_daily import _local_today

router = APIRouter(prefix="/usage")

# Internal-only fields stripped before returning rows to the API layer
# (per the ID convention: never expose integer id / user_id).
_INTERNAL_FIELDS = ("id", "user_id")


@router.get("/model-daily")
async def list_model_daily(
    request: Request,
    source: Optional[str] = Query("crs"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(1000),
):
    """Per-model daily usage rows. Defaults to source='crs' and today's date
    (the freshest CRS snapshot) when no range is given. Thin passthrough to
    service.list_for; multi-day aggregation is done client-side."""
    user_id = request.state.user_id
    today = _local_today()
    rows = usage_service.list_for(
        user_id,
        source=source,
        from_date=from_date or today,
        to_date=to_date or today,
        limit=limit,
    )
    return [
        {k: v for k, v in row.to_dict().items() if k not in _INTERNAL_FIELDS}
        for row in rows
    ]
