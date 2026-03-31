from fastapi import APIRouter, Request
from pydantic import BaseModel

from storage.service import link_todo_relation as relation_service

router = APIRouter(prefix="/link-todo")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class RelationRequest(BaseModel):
    link_id: str
    todo_id: str


@router.post("")
async def create_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    created = relation_service.create_relation(user_id, req.link_id, req.todo_id)
    return {"ok": True, "created": created}


@router.post("/delete")
async def delete_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    deleted = relation_service.delete_relation(user_id, req.link_id, req.todo_id)
    return {"ok": True, "deleted": deleted}


@router.get("/by-todo")
async def list_by_todo(request: Request, todo_id: str):
    user_id = _get_user_id(request)
    link_ids = relation_service.list_by_todo(user_id, todo_id)
    return link_ids


@router.get("/by-link")
async def list_by_link(request: Request, link_id: str):
    user_id = _get_user_id(request)
    todo_ids = relation_service.list_by_link(user_id, link_id)
    return todo_ids
