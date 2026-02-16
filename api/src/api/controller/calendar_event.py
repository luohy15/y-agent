from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from storage.service import calendar_event as event_service
from storage.database.base import get_db
from storage.entity.todo import TodoEntity

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
    todo_id: Optional[int] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(200),
):
    user_id = _get_user_id(request)
    events = event_service.list_events(
        user_id, date=date, start=start, end=end,
        source=source, todo_id=todo_id,
        include_deleted=include_deleted, limit=limit,
    )
    results = [e.to_dict() for e in events]
    # Resolve todo PK ids to todo_id strings
    todo_pks = {e.todo_id for e in events if e.todo_id is not None}
    if todo_pks:
        with get_db() as session:
            rows = session.query(TodoEntity.id, TodoEntity.todo_id).filter(TodoEntity.id.in_(todo_pks)).all()
            pk_to_tid = {row.id: row.todo_id for row in rows}
        for r in results:
            if r.get("todo_id") in pk_to_tid:
                r["linked_todo_id"] = pk_to_tid[r["todo_id"]]
    return results


@router.get("/detail")
async def get_event(request: Request, event_id: str = Query(...)):
    user_id = _get_user_id(request)
    event = event_service.get_event(user_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.to_dict()
