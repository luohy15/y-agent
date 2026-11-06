import base64
import binascii

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from storage.service import skill_share
from storage.skill_bundle import MAX_BYTES

router = APIRouter(prefix='/skill')


class PublishRequest(BaseModel):
    name: str = Field(max_length=64)
    bundle: str = Field(max_length=((MAX_BYTES + 2) // 3) * 4)
    bundle_sha: str = Field(min_length=64, max_length=64)
    manifest: dict
    nodes: list[str] = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=128)


class UnshareRequest(BaseModel):
    name: str = Field(max_length=64)


@router.post('/publish')
def publish(req: PublishRequest, request: Request):
    try:
        data = base64.b64decode(req.bundle, validate=True)
        return skill_share.publish(request.state.user_id, req.name, data, req.manifest,
                                   req.bundle_sha, req.nodes, req.version)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get('/list')
def list_pins(request: Request):
    return skill_share.list_pins(request.state.user_id)


@router.post('/unshare')
def unshare(req: UnshareRequest, request: Request):
    try:
        return skill_share.unshare(request.state.user_id, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
