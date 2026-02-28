from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import calendar_event as event_service

router = APIRouter(prefix="/calendar")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateEventRequest(BaseModel):
    summary: str
    start: str
    end: Optional[str] = None
    description: Optional[str] = None
    todo_id: Optional[str] = None
    all_day: bool = False
    source: Optional[str] = None


class UpdateEventRequest(BaseModel):
    event_id: str
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    todo_id: Optional[str] = None


class EventIdRequest(BaseModel):
    event_id: str


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


@router.post("")
async def create_event(req: CreateEventRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        event = event_service.add_event(
            user_id, req.summary, req.start,
            end_time=req.end, description=req.description,
            todo_id=req.todo_id, all_day=req.all_day, source=req.source,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event.to_dict()


@router.post("/update")
async def update_event(req: UpdateEventRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"event_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        event = event_service.update_event(user_id, req.event_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.to_dict()


@router.post("/delete")
async def delete_event(req: EventIdRequest, request: Request):
    user_id = _get_user_id(request)
    event = event_service.delete_event(user_id, req.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.to_dict()


@router.post("/restore")
async def restore_event(req: EventIdRequest, request: Request):
    user_id = _get_user_id(request)
    event = event_service.restore_event(user_id, req.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found or not deleted")
    return event.to_dict()


@router.get("/deleted")
async def list_deleted_events(
    request: Request,
    limit: int = Query(50),
):
    user_id = _get_user_id(request)
    events = event_service.list_deleted_events(user_id, limit=limit)
    return [e.to_dict() for e in events]
