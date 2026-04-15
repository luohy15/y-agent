from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import note as note_service

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
    deleted = note_service.delete_note(user_id, req.note_id)
    return {"ok": True, "deleted": deleted}


@router.get("/detail")
async def get_note(request: Request, note_id: str = Query(...)):
    user_id = _get_user_id(request)
    note = note_service.get_note(user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note.to_dict()


@router.get("/list")
async def list_notes(request: Request, limit: int = Query(50), offset: int = Query(0)):
    user_id = _get_user_id(request)
    notes = note_service.list_notes(user_id, limit=limit, offset=offset)
    return [n.to_dict() for n in notes]
