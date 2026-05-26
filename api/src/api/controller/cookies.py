from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import user_cookies as user_cookies_service

router = APIRouter(prefix="/cookies")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class UpsertCookiesRequest(BaseModel):
    domain: str
    cookies_txt: str


@router.put("")
async def upsert_cookies(req: UpsertCookiesRequest, request: Request):
    user_id = _get_user_id(request)
    row = user_cookies_service.upsert_cookies(user_id, req.domain, req.cookies_txt)
    return row.to_dict(include_blob=False)


@router.get("")
async def get_or_list_cookies(request: Request, domain: Optional[str] = Query(None)):
    user_id = _get_user_id(request)
    if domain:
        row = user_cookies_service.get_cookies(user_id, domain)
        if row is None:
            raise HTTPException(status_code=404, detail="Cookies not found")
        return row.to_dict(include_blob=True)
    return [row.to_dict(include_blob=False) for row in user_cookies_service.list_cookies(user_id)]


@router.delete("")
async def delete_cookies(request: Request, domain: str = Query(...)):
    user_id = _get_user_id(request)
    return {"deleted": user_cookies_service.delete_cookies(user_id, domain)}
