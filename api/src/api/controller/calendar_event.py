from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from storage.service import calendar_event as event_service

router = APIRouter(prefix="/calendar")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def list_events(
    request: Request,
    date: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    todo_id: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(200),
):
    user_id = _get_user_id(request)
    events = event_service.list_events(
        user_id, date=date, start=start, end=end,
        source=source, todo_id=todo_id,
        include_deleted=include_deleted, limit=limit,
    )
    return [e.to_dict() for e in events]


@router.get("/detail")
async def get_event(request: Request, event_id: str = Query(...)):
    user_id = _get_user_id(request)
    event = event_service.get_event(user_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.to_dict()
