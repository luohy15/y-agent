from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from storage.service import remote_job as service

router = APIRouter(prefix='/remote-jobs')


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TargetRequest(StrictRequest):
    target_id: str = 'mac'
    transport_kind: str = 'ssh_alias'
    transport_ref: str = 'mac'
    platform: str = 'macos'
    executors: list[str] = ['codex']
    operations: list[str] = ['browser_open']
    enabled: bool = True


class SubmitRequest(StrictRequest):
    target: str = 'mac'
    executor: str = 'codex'
    operation: str = 'browser_open'
    payload: dict
    timeout_seconds: int = Field(180, ge=1, le=600)
    todo_id: str | None = None
    trace_id: str | None = None
    callback_chat_id: str | None = None


class HeartbeatRequest(StrictRequest):
    attempt: int = Field(ge=1)
    claim_token: str
    state: str = 'running'


class FinishRequest(HeartbeatRequest):
    termination_confirmed: bool = False
    exit_code: int | None = None
    error_code: str | None = None
    error: str | None = Field(None, max_length=16000)
    stdout: str | None = Field(None, max_length=65536)
    stderr: str | None = Field(None, max_length=65536)
    result: dict | None = None
    artifacts: list[dict] | None = None


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/targets')
async def targets(request: Request):
    return service.list_targets(request.state.user_id)


@router.post('/targets')
async def target(body: TargetRequest, request: Request):
    return call(service.add_target, request.state.user_id, body.model_dump())


@router.get('')
async def jobs(request: Request, limit: int = Query(50, ge=1, le=100)):
    return service.list_jobs(request.state.user_id, limit)


@router.post('')
async def submit(body: SubmitRequest, request: Request):
    try:
        return await service.submit(request.state.user_id, **body.model_dump())
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/reap')
async def reap(request: Request):
    return service.reap(request.state.user_id)


@router.get('/{job_id}')
async def get(job_id: str, request: Request):
    return call(service.get, request.state.user_id, job_id)


@router.get('/{job_id}/result')
async def result(job_id: str, request: Request):
    return call(service.get, request.state.user_id, job_id)


@router.post('/{job_id}/cancel')
async def cancel(job_id: str, request: Request):
    return call(service.cancel, request.state.user_id, job_id)


@router.post('/{job_id}/claim')
async def claim(job_id: str, request: Request):
    return call(service.claim, request.state.user_id, job_id)


@router.post('/{job_id}/heartbeat')
async def heartbeat(job_id: str, body: HeartbeatRequest, request: Request):
    return call(service.heartbeat, request.state.user_id, job_id, **body.model_dump())


@router.post('/{job_id}/finish')
async def finish(job_id: str, body: FinishRequest, request: Request):
    return call(service.finish, request.state.user_id, job_id, **body.model_dump())
