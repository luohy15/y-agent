from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from storage.service import upload_job as uploads
from storage.service import user as users

router = APIRouter(prefix="/upload")


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    filename: str
    size_bytes: StrictInt
    checksum_sha256_b64: str
    dest_dir: str
    vm_name: str = "default"
    work_dir: str | None = None
    overwrite_ack: StrictBool = False


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except uploads.UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


def _public_user_id(request: Request) -> str:
    public_user_id = users.get_live_public_user_id(request.state.user_id)
    if not public_user_id:
        raise HTTPException(status_code=401, detail="The authenticated user was not found.")
    return public_user_id


@router.post("/authorize")
def authorize(req: AuthorizeRequest, request: Request):
    return _call(uploads.authorize, _public_user_id(request), **req.model_dump())


@router.get("/active")
def active(request: Request):
    return _call(uploads.get_active, _public_user_id(request))


@router.get("/batch/{batch_id}")
def batch(batch_id: str, request: Request):
    return _call(uploads.get_batch, _public_user_id(request), batch_id)


@router.post("/{upload_id}/retry")
def retry(upload_id: str, request: Request):
    return _call(uploads.retry_upload, _public_user_id(request), upload_id)
