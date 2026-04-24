from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import entity as entity_service
from storage.service import entity_note_relation as note_relation_service
from storage.service import entity_rss_relation as rss_relation_service
from storage.service import entity_link_relation as link_relation_service

router = APIRouter(prefix="/entity")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateEntityRequest(BaseModel):
    name: str
    type: str
    front_matter: Optional[Dict] = None


class UpdateEntityRequest(BaseModel):
    entity_id: str
    name: Optional[str] = None
    type: Optional[str] = None
    front_matter: Optional[Dict] = None


class ImportEntityRequest(BaseModel):
    name: str
    type: str
    front_matter: Optional[Dict] = None


class DeleteEntityRequest(BaseModel):
    entity_id: str


@router.post("")
async def create_entity(req: CreateEntityRequest, request: Request):
    user_id = _get_user_id(request)
    entity = entity_service.create_entity(user_id, req.name, req.type, front_matter=req.front_matter)
    return entity.to_dict()


@router.post("/import")
async def import_entity(req: ImportEntityRequest, request: Request):
    user_id = _get_user_id(request)
    entity = entity_service.import_entity(user_id, req.name, req.type, front_matter=req.front_matter)
    return entity.to_dict()


@router.post("/update")
async def update_entity(req: UpdateEntityRequest, request: Request):
    user_id = _get_user_id(request)
    entity = entity_service.update_entity(
        user_id,
        req.entity_id,
        name=req.name,
        type=req.type,
        front_matter=req.front_matter,
    )
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.to_dict()


@router.post("/delete")
async def delete_entity(req: DeleteEntityRequest, request: Request):
    user_id = _get_user_id(request)
    deleted = entity_service.delete_entity(user_id, req.entity_id)
    return {"ok": True, "deleted": deleted}


@router.get("/detail")
async def get_entity(request: Request, entity_id: str = Query(...)):
    user_id = _get_user_id(request)
    entity = entity_service.get_entity(user_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.to_dict()


@router.get("/list")
async def list_entities(
    request: Request,
    limit: int = Query(50),
    offset: int = Query(0),
    type: Optional[str] = Query(None),
    note_id: Optional[str] = Query(None),
    rss_feed_id: Optional[str] = Query(None),
    activity_id: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    if note_id:
        entity_ids = note_relation_service.list_by_note(user_id, note_id)
        if not entity_ids:
            return []
        entities = entity_service.get_entities_by_ids(user_id, entity_ids)
        return [e.to_dict() for e in entities]
    if rss_feed_id:
        entity_ids = rss_relation_service.list_by_feed(user_id, rss_feed_id)
        if not entity_ids:
            return []
        entities = entity_service.get_entities_by_ids(user_id, entity_ids)
        return [e.to_dict() for e in entities]
    if activity_id:
        entity_ids = link_relation_service.list_by_activity(user_id, activity_id)
        if not entity_ids:
            return []
        entities = entity_service.get_entities_by_ids(user_id, entity_ids)
        return [e.to_dict() for e in entities]
    entities = entity_service.list_entities(user_id, limit=limit, offset=offset, type=type)
    return [e.to_dict() for e in entities]
