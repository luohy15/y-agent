from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from storage.service import entity_rss_relation as relation_service

router = APIRouter(prefix="/entity-rss")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class RelationRequest(BaseModel):
    entity_id: str
    rss_feed_id: str


@router.post("")
async def create_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    created = relation_service.create_relation(user_id, req.entity_id, req.rss_feed_id)
    return {"ok": True, "created": created}


@router.post("/delete")
async def delete_relation(req: RelationRequest, request: Request):
    user_id = _get_user_id(request)
    deleted = relation_service.delete_relation(user_id, req.entity_id, req.rss_feed_id)
    return {"ok": True, "deleted": deleted}


@router.get("/by-entity")
async def list_by_entity(request: Request, entity_id: str = Query(...)):
    user_id = _get_user_id(request)
    rss_feed_ids = relation_service.list_by_entity(user_id, entity_id)
    return rss_feed_ids


@router.get("/by-feed")
async def list_by_feed(request: Request, rss_feed_id: str = Query(...)):
    user_id = _get_user_id(request)
    entity_ids = relation_service.list_by_feed(user_id, rss_feed_id)
    return entity_ids
