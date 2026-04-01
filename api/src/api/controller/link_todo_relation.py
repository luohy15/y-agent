from typing import List

from fastapi import APIRouter, Request
from pydantic import BaseModel

from storage.service import link_todo_relation as relation_service

router = APIRouter(prefix="/link-todo")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class RelationRequest(BaseModel):
    activity_id: str
    todo_id: str


class BatchRelationRequest(BaseModel):
    activity_ids: List[str]
    todo_id: str


@router.post("")
async def create_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    created = relation_service.create_relation(user_id, req.activity_id, req.todo_id)
    return {"ok": True, "created": created}


@router.post("/batch")
async def batch_create_relations(req: BatchRelationRequest, request: Request):
    user_id = _get_user_id(request)
    count = relation_service.batch_create_relations(user_id, req.activity_ids, req.todo_id)
    return {"ok": True, "created": count}


@router.post("/delete")
async def delete_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    deleted = relation_service.delete_relation(user_id, req.activity_id, req.todo_id)
    return {"ok": True, "deleted": deleted}


@router.get("/by-todo")
async def list_by_todo(request: Request, todo_id: str):
    user_id = _get_user_id(request)
    activity_ids = relation_service.list_by_todo(user_id, todo_id)
    return activity_ids


@router.get("/by-activity")
async def list_by_activity(request: Request, activity_id: str):
    user_id = _get_user_id(request)
    todo_ids = relation_service.list_by_activity(user_id, activity_id)
    return todo_ids
