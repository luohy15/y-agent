from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import tg_topic as tg_topic_service

router = APIRouter(prefix="/tg-topic")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class AddTopicRequest(BaseModel):
    group_id: int
    topic_name: str
    topic_icon: Optional[str] = None


class ImportTopicItem(BaseModel):
    topic_name: str
    topic_id: Optional[int] = None
    topic_icon: Optional[str] = None


class ImportTopicsRequest(BaseModel):
    group_id: int
    topics: List[ImportTopicItem]


@router.get("/list")
async def list_topics(request: Request, group_id: int = Query(...)):
    user_id = _get_user_id(request)
    topics = tg_topic_service.list_topics(user_id, group_id)
    return [t.to_dict() for t in topics]


@router.post("")
async def add_topic(req: AddTopicRequest, request: Request):
    user_id = _get_user_id(request)
    topic = tg_topic_service.add_topic(user_id, req.group_id, req.topic_name, topic_icon=req.topic_icon)
    return topic.to_dict()


@router.post("/import")
async def import_topics(req: ImportTopicsRequest, request: Request):
    """Batch import existing topics (upsert by name)."""
    user_id = _get_user_id(request)
    topics = tg_topic_service.import_topics(
        user_id, req.group_id,
        [t.model_dump() for t in req.topics],
    )
    return [t.to_dict() for t in topics]


@router.post("/delete/{pk_id}")
async def delete_topic(pk_id: int, request: Request):
    user_id = _get_user_id(request)
    ok = tg_topic_service.delete_topic(user_id, pk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"ok": True}


@router.post("/sync")
async def sync_topics(request: Request, group_id: int = Query(...)):
    user_id = _get_user_id(request)
    topics = await tg_topic_service.sync_topics(user_id, group_id)
    return [t.to_dict() for t in topics]
