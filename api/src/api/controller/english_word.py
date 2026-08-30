from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import english_word as vocab_service

router = APIRouter(prefix="/english/vocab")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class MarkRequest(BaseModel):
    status: str
    word_ids: Optional[List[str]] = None
    words: Optional[List[str]] = None


@router.post("/seed")
async def seed_words(request: Request):
    user_id = _get_user_id(request)
    return vocab_service.seed_words(user_id)


@router.get("/list")
async def list_words(
    request: Request,
    status: Optional[str] = Query(None),
    max_rank: Optional[int] = Query(None),
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
    try:
        rows = vocab_service.list_words(
            user_id,
            status=status,
            max_rank=max_rank,
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [r.to_dict() for r in rows]


@router.post("/mark")
async def mark_words(req: MarkRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        rows = vocab_service.mark_words(
            user_id,
            status=req.status,
            word_ids=req.word_ids,
            words=req.words,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [r.to_dict() for r in rows]


@router.get("/stats")
async def vocab_stats(request: Request):
    user_id = _get_user_id(request)
    return vocab_service.stats(user_id)
