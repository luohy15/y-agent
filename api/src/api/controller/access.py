from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.util.google_identity import GoogleIdentityError, verify_google_id_token
from storage.service.user import get_live_public_user_id
from storage.service.user_access import (
    approve as approve_access,
    inventory as access_inventory,
    list_applications,
    record_request,
    resolve_maintainer,
)

router = APIRouter(prefix="/access", tags=["access"])


class AccessRequestBody(BaseModel):
    id_token: str


class ApproveBody(BaseModel):
    email: str


def _require_maintainer(request: Request) -> dict:
    maintainer = resolve_maintainer()
    user_id = getattr(request.state, "user_id", None)
    if maintainer["internal_id"] is None or user_id != maintainer["internal_id"]:
        raise HTTPException(status_code=403, detail="Maintainer only")
    return maintainer


@router.post("/request")
async def request_access(body: AccessRequestBody):
    try:
        identity = verify_google_id_token(body.id_token)
    except GoogleIdentityError as exc:
        raise HTTPException(status_code=401, detail="Invalid Google ID token") from exc
    return record_request(identity["email"])


@router.get("/applications")
async def applications(request: Request, status: Annotated[Optional[str], Query()] = None):
    _require_maintainer(request)
    if status is not None and status not in {"pending", "approved"}:
        raise HTTPException(status_code=422, detail="status must be pending or approved")
    return list_applications(status)


@router.post("/applications/approve")
async def approve(request: Request, body: ApproveBody):
    maintainer = _require_maintainer(request)
    decided_by = maintainer["public_id"] or get_live_public_user_id(request.state.user_id) or ""
    row = approve_access(body.email, decided_by)
    if row is None:
        raise HTTPException(status_code=404, detail="No application for that email")
    return row


@router.get("/inventory")
async def inventory(request: Request):
    _require_maintainer(request)
    return access_inventory()
