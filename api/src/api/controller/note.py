from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import note as note_service
from storage.service import note_todo_relation as relation_service

router = APIRouter(prefix="/note")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateNoteRequest(BaseModel):
    content_key: str
    front_matter: Optional[Dict] = None


class UpdateNoteRequest(BaseModel):
    note_id: str
    content_key: Optional[str] = None
    front_matter: Optional[Dict] = None


class ImportNoteRequest(BaseModel):
    content_key: str
    front_matter: Optional[Dict] = None


class DeleteNoteRequest(BaseModel):
    note_id: str
    force: bool = False


@router.post("")
async def create_note(req: CreateNoteRequest, request: Request):
    user_id = _get_user_id(request)
    note = note_service.create_note(user_id, req.content_key, front_matter=req.front_matter)
    return note.to_dict()


@router.post("/import")
async def import_note(req: ImportNoteRequest, request: Request):
    user_id = _get_user_id(request)
    note = note_service.import_note(user_id, req.content_key, front_matter=req.front_matter)
    return note.to_dict()


@router.post("/update")
async def update_note(req: UpdateNoteRequest, request: Request):
    user_id = _get_user_id(request)
    note = note_service.update_note(user_id, req.note_id, content_key=req.content_key, front_matter=req.front_matter)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note.to_dict()


@router.post("/delete")
async def delete_note(req: DeleteNoteRequest, request: Request):
    user_id = _get_user_id(request)
    result = note_service.delete_note(user_id, req.note_id, force=req.force)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/detail")
async def get_note(request: Request, note_id: str = Query(...), include_deleted: bool = Query(False)):
    user_id = _get_user_id(request)
    note = note_service.get_note(user_id, note_id, include_deleted=include_deleted)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note.to_dict()


@router.get("/list")
async def list_notes(
    request: Request,
    limit: int = Query(50),
    offset: int = Query(0),
    todo_id: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    if todo_id:
        note_ids = relation_service.list_by_todo(user_id, todo_id)
        if not note_ids:
            return []
        notes = note_service.get_notes_by_ids(user_id, note_ids, include_deleted=include_deleted)
        return [n.to_dict() for n in notes]
    notes = note_service.list_notes(
        user_id, limit=limit, offset=offset, include_deleted=include_deleted,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )
    return [n.to_dict() for n in notes]
