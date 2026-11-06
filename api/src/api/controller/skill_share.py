import base64
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from storage.service import skill_share
from storage.repository.skill_share import SkillConflict, SkillNotFound
from storage.skill_bundle import MAX_BYTES

router = APIRouter(prefix='/skill')


@contextmanager
def errors():
    try:
        yield
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class PublishRequest(BaseModel):
    name: str = Field(max_length=64)
    bundle: str = Field(max_length=((MAX_BYTES + 2) // 3) * 4)
    bundle_sha: str = Field(min_length=64, max_length=64)
    manifest: dict
    version: str = Field(max_length=64)
    source_commit: str = Field(max_length=40)
    source_repo: str = Field(max_length=512)


class InstallRequest(BaseModel):
    name: str = Field(max_length=64)
    node: str = Field(max_length=64)
    version: str | None = Field(default=None, max_length=64)


@router.post('/publish')
def publish(req: PublishRequest, request: Request):
    with errors():
        data = base64.b64decode(req.bundle, validate=True)
        return skill_share.publish(request.state.user_id, req.name, data, req.manifest,
                                   req.bundle_sha, req.version, req.source_commit, req.source_repo)


@router.get('/list')
def list_skills(request: Request):
    return skill_share.list_skills(request.state.user_id)


@router.get('/show')
def show(request: Request, name: str, version: str | None = None):
    with errors():
        return skill_share.show(request.state.user_id, name, version)


@router.get('/status')
def status(request: Request, node: str | None = None):
    return skill_share.list_installs(request.state.user_id, node)


def _change(req, request, operation):
    with errors():
        return skill_share.change_install(request.state.user_id, req.name, req.node, operation, req.version)


@router.post('/install')
def install(req: InstallRequest, request: Request):
    return _change(req, request, 'install')


@router.post('/upgrade')
def upgrade(req: InstallRequest, request: Request):
    return _change(req, request, 'upgrade')


@router.post('/rollback')
def rollback(req: InstallRequest, request: Request):
    return _change(req, request, 'rollback')


@router.post('/uninstall')
def uninstall(req: InstallRequest, request: Request):
    return _change(req, request, 'uninstall')
