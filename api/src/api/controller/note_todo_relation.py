from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from storage.service import note_todo_relation as relation_service

router = APIRouter(prefix="/note-todo")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class RelationRequest(BaseModel):
    note_id: str
    todo_id: str


@router.post("")
async def create_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    created = relation_service.create_relation(user_id, req.note_id, req.todo_id)
    return {"ok": True, "created": created}


@router.post("/delete")
async def delete_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    deleted = relation_service.delete_relation(user_id, req.note_id, req.todo_id)
    return {"ok": True, "deleted": deleted}


@router.get("/by-todo")
async def list_by_todo(request: Request, todo_id: str = Query(...)):
    user_id = _get_user_id(request)
    note_ids = relation_service.list_by_todo(user_id, todo_id)
    return note_ids


@router.get("/by-note")
async def list_by_note(request: Request, note_id: str = Query(...)):
    user_id = _get_user_id(request)
    todo_ids = relation_service.list_by_note(user_id, note_id)
    return todo_ids
