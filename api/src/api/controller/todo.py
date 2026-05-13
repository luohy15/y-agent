from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import todo as todo_service

router = APIRouter(prefix="/todo")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateTodoRequest(BaseModel):
    name: str
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None


class UpdateTodoRequest(BaseModel):
    todo_id: str
    name: Optional[str] = None
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[str] = None
    status: Optional[str] = None


class TodoIdRequest(BaseModel):
    todo_id: str


@router.get("/list")
async def list_todos(
    request: Request,
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    unread: Optional[bool] = Query(None),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    user_id = _get_user_id(request)
    todos = todo_service.list_todos(
        user_id,
        status=status,
        priority=priority,
        query=query,
        unread=unread,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
        limit=limit,
        offset=offset,
    )
    result = [t.to_dict() for t in todos]

    # Batch-lookup chat status for all todo_ids (trace_id == todo_id)
    todo_ids = [t.todo_id for t in todos]
    if todo_ids:
        from storage.repository.chat import get_trace_chat_status
        chat_status = get_trace_chat_status(user_id, todo_ids)
        for item in result:
            cs = chat_status.get(item["todo_id"], {})
            item["has_running"] = cs.get("has_running", False)
            item["has_unread"] = cs.get("has_unread", False)

    return result


@router.get("/detail")
async def get_todo(request: Request, todo_id: str = Query(...)):
    user_id = _get_user_id(request)
    todo = todo_service.get_todo(user_id, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    result = todo.to_dict()

    # Include associated notes
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note import get_notes_by_ids
    note_ids = list_note_relations(user_id, todo_id)
    if note_ids:
        result["notes"] = [n.to_dict() for n in get_notes_by_ids(user_id, note_ids)]
    return result


@router.post("")
async def create_todo(req: CreateTodoRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.create_todo(
        user_id, req.name, desc=req.desc, tags=req.tags,
        due_date=req.due_date, priority=req.priority,
    )
    return todo.to_dict()


@router.post("/update")
async def update_todo(req: UpdateTodoRequest, request: Request):
    user_id = _get_user_id(request)
    fields = req.model_dump(exclude={"todo_id"}, exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    status = fields.pop("status", None)
    todo = None
    if status is not None:
        todo = todo_service.update_status(user_id, req.todo_id, status)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")
    if fields:
        todo = todo_service.update_todo(user_id, req.todo_id, **fields)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


class PinTodoRequest(BaseModel):
    todo_id: str
    pinned: bool


@router.post("/pin")
async def pin_todo(req: PinTodoRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.pin_todo(user_id, req.todo_id, req.pinned)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


class UpdateStatusRequest(BaseModel):
    todo_id: str
    status: str


@router.post("/status")
async def update_status(req: UpdateStatusRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.update_status(user_id, req.todo_id, req.status)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()
