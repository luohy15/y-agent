from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from storage.service import user_preference as user_pref_service

router = APIRouter(prefix="/user-preference")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class UpsertPreferenceRequest(BaseModel):
    key: str
    value: Optional[Any] = None


def _empty_response(key: str) -> dict:
    return {"key": key, "value": None, "updated_at": None}


@router.get("")
async def get_preference(request: Request, key: str = Query(...)):
    user_id = _get_user_id(request)
    pref = user_pref_service.get_preference(user_id, key)
    if pref is None:
        return _empty_response(key)
    return pref.to_dict()


@router.put("")
async def upsert_preference(req: UpsertPreferenceRequest, request: Request):
    user_id = _get_user_id(request)
    pref = user_pref_service.upsert_preference(user_id, req.key, req.value)
    return pref.to_dict()


@router.delete("")
async def delete_preference(request: Request, key: str = Query(...)):
    user_id = _get_user_id(request)
    deleted = user_pref_service.delete_preference(user_id, key)
    return {"deleted": deleted}
