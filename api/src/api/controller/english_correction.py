from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from storage.service import english_correction as eng_service

router = APIRouter(prefix="/english")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class AddCorrectionRequest(BaseModel):
    chat_id: str
    message_id: str
    message_at: str
    message_at_unix: int
    original_text: str
    corrected_text: str
    error_categories: List[str] = Field(default_factory=list)
    explanation: str


class DismissRequest(BaseModel):
    correction_id: str


class MarkScannedRequest(BaseModel):
    scanned_through_unix: int


@router.get("/list")
async def list_corrections(
    request: Request,
    dismissed: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
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
    rows = eng_service.list_corrections(
        user_id,
        dismissed=dismissed,
        category=category,
        query=query,
        limit=limit,
        offset=offset,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
    )
    return [r.to_dict() for r in rows]


@router.get("/detail")
async def get_correction(request: Request, correction_id: str = Query(...)):
    user_id = _get_user_id(request)
    row = eng_service.get_correction(user_id, correction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Correction not found")
    return row.to_dict()


@router.post("")
async def add_correction(req: AddCorrectionRequest, request: Request):
    user_id = _get_user_id(request)
    row = eng_service.add_correction(
        user_id,
        chat_id=req.chat_id,
        message_id=req.message_id,
        message_at=req.message_at,
        message_at_unix=req.message_at_unix,
        original_text=req.original_text,
        corrected_text=req.corrected_text,
        error_categories=req.error_categories,
        explanation=req.explanation,
    )
    return row.to_dict()


@router.post("/dismiss")
async def dismiss_correction(req: DismissRequest, request: Request):
    user_id = _get_user_id(request)
    row = eng_service.dismiss_correction(user_id, req.correction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Correction not found")
    return row.to_dict()


@router.get("/pending")
async def list_pending(
    request: Request,
    limit: int = Query(50),
    since: Optional[int] = Query(default=None, description="Unix ms lower bound (exclusive)"),
):
    user_id = _get_user_id(request)
    # FastAPI injects Query defaults; when called directly in unit tests the
    # default may be a Query object — normalize to a plain int/None.
    since_unix = since if isinstance(since, int) else None
    return eng_service.list_pending(user_id, since_unix=since_unix, limit=limit)


@router.post("/mark-scanned")
async def mark_scanned(req: MarkScannedRequest, request: Request):
    user_id = _get_user_id(request)
    return eng_service.set_watermark(user_id, req.scanned_through_unix)
