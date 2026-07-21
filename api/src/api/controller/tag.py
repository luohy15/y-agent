from typing import List

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from storage.service import tag as tag_service

router = APIRouter(prefix="/tag")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class WriteTagsRequest(BaseModel):
    entity_type: str
    entity_id: str
    tags: List[str]


@router.get("")
async def get_by_tag(request: Request, tag: str = Query(...), prefix: bool = Query(False)):
    user_id = _get_user_id(request)
    return tag_service.get_by_tag(user_id, tag, prefix=prefix)


@router.get("/list")
async def list_tags(request: Request):
    user_id = _get_user_id(request)
    vocabulary = tag_service.list_vocabulary(user_id)
    return [{"tag": t, "count": c} for t, c in vocabulary]


@router.post("/add")
async def add_tags(req: WriteTagsRequest, request: Request):
    user_id = _get_user_id(request)
    added = [t for t in req.tags if tag_service.add_tag(user_id, req.entity_type, req.entity_id, t)]
    return {"added": added}


@router.post("/remove")
async def remove_tags(req: WriteTagsRequest, request: Request):
    user_id = _get_user_id(request)
    removed = [t for t in req.tags if tag_service.remove_tag(user_id, req.entity_type, req.entity_id, t)]
    return {"removed": removed}
