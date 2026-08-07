import os
from pathlib import Path
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from agent.vm_command import run_vm_command as _exec
from storage.service import note as note_service

router = APIRouter(prefix="/note")

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateShareRequest(BaseModel):
    note_id: str
    password: Optional[str] = None
    generate_password: bool = False


def _agent_home() -> Path:
    return Path(os.environ.get("Y_AGENT_HOME", str(Path.home()))).resolve()


def _validate_content_key(content_key: str) -> None:
    home = _agent_home()
    path = (home / content_key).resolve()
    if home != path and home not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid content key")


def _snapshot_s3_key(note_id: str) -> str:
    return f"notes/{note_id}/content.md"


async def _snapshot_note_content(user_id: int, note_id: str, content_key: str) -> str:
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="Y_AGENT_S3_BUCKET is not configured")
    _validate_content_key(content_key)
    try:
        content = await _exec(user_id, ["cat", content_key], timeout=30)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Note content not found") from exc
    s3_key = _snapshot_s3_key(note_id)
    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown",
    )
    return s3_key


def _delete_note_snapshot(note_id: str) -> None:
    if not S3_BUCKET:
        return
    try:
        boto3.client("s3").delete_object(Bucket=S3_BUCKET, Key=_snapshot_s3_key(note_id))
    except ClientError:
        pass


def _read_note_snapshot(note_id: str) -> str:
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="Y_AGENT_S3_BUCKET is not configured")
    try:
        obj = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=_snapshot_s3_key(note_id))
        return obj["Body"].read().decode("utf-8")
    except ClientError as exc:
        raise HTTPException(status_code=404, detail="Note content not found") from exc


async def share_note(
    user_id: int,
    note_id: str,
    password: Optional[str] = None,
    generate_password: bool = False,
) -> Dict:
    """Snapshot a note's content to S3 and ensure a note_share row exists.

    Reusable across controllers (note.py create_share + trace.py batch share).
    Does get_note (ownership check) -> _snapshot_note_content (S3, API concern)
    -> note_share service (pure DB). Returns {share_id, password?}.
    """
    from storage import share_password as sp
    from storage.service import note_share as note_share_service

    note = note_service.get_note(user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await _snapshot_note_content(user_id, note_id, note.content_key)

    generated_password: Optional[str] = None
    password_hash: Optional[str] = None
    if generate_password and not (password and password.strip()):
        generated_password = sp.generate_password()
        password_hash = sp.hash_password(generated_password)
    elif password and password.strip():
        password_hash = sp.hash_password(password)

    share_id, _ = note_share_service.ensure_share(user_id, note_id, password_hash=password_hash)
    resp: Dict = {"share_id": share_id}
    if generated_password is not None:
        resp["password"] = generated_password
    return resp


@router.post("/share")
async def create_share(req: CreateShareRequest, request: Request):
    user_id = _get_user_id(request)
    return await share_note(
        user_id,
        req.note_id,
        password=req.password,
        generate_password=req.generate_password,
    )


def revoke_note_share(share) -> None:
    """Soft-revoke a note share: drop its S3 snapshot + flip revoked_at (keeps the
    random share_id token so reshare reuses the same /n/<id> URL). Reusable across
    controllers (note.py delete_share + trace.py delete_share cascade). Caller
    checks ownership."""
    from storage.repository.note_share import set_revoked
    from storage.util import get_utc_iso8601_timestamp

    _delete_note_snapshot(share.note_id)
    set_revoked(share.share_id, get_utc_iso8601_timestamp())


@router.delete("/share")
async def delete_share(request: Request, share_id: str = Query(...)):
    from storage.repository.note_share import get_by_share_id

    user_id = _get_user_id(request)
    share = get_by_share_id(share_id)
    if not share or share.user_id != user_id:
        raise HTTPException(status_code=404, detail="Share not found")
    revoke_note_share(share)
    return {"deleted": True}


@router.get("/share/mine")
async def get_my_share(request: Request, note_id: str = Query(...)):
    from storage.repository.note_share import get_by_note_id

    user_id = _get_user_id(request)
    share = get_by_note_id(user_id, note_id)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    return {
        "share_id": share.share_id,
        "note_id": share.note_id,
        "has_password": bool(share.password_hash),
    }


@router.get("/shares")
async def list_shares(request: Request):
    from storage.repository.note_share import list_by_user

    user_id = _get_user_id(request)
    shares = list_by_user(user_id)
    return [
        {
            "share_id": share.share_id,
            "note_id": share.note_id,
            "has_password": bool(share.password_hash),
        }
        for share in shares
    ]


@router.get("/share")
async def get_share(share_id: str = Query(...), password: Optional[str] = Query(None)):
    from storage import share_password as sp
    from storage.repository.note_share import get_by_share_id

    share = get_by_share_id(share_id)
    if not share or share.revoked_at:
        raise HTTPException(status_code=404, detail="Share not found")

    if share.password_hash:
        if not password:
            raise HTTPException(status_code=401, detail={"password_required": True})
        allowed, retry_after = sp.check_rate_limit(share_id)
        if not allowed:
            raise HTTPException(status_code=429, detail={"retry_after": retry_after})
        if not sp.verify_password(password, share.password_hash):
            sp.record_failure(share_id)
            raise HTTPException(status_code=403, detail="Invalid password")

    note = note_service.get_note(share.user_id, share.note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    data = note.to_dict()
    data["content"] = _read_note_snapshot(note.note_id)
    return data
