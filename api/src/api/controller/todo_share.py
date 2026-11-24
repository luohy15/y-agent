import os
from pathlib import Path
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from agent.vm_command import run_vm_command
from api.controller.link import _read_link_content
from storage.crypto.blob import open_body, seal_body
from storage.repository import link as link_repo
from storage.repository import note as note_repo
from storage.repository.chat import get_chat, get_chat_metas
from storage.service import todo_share as share_service
from storage.service.todo_share import TodoShareError, note_title

router = APIRouter(prefix="/todo", tags=["todo-share"])

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")
NOTE_LIMIT = 1_000_000


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class ShareTodoRequest(BaseModel):
    todo_id: str
    to: str
    notes: Optional[List[str]] = None
    chats: Optional[List[str]] = None
    links: Optional[List[str]] = None
    clear_items: bool = False


class VisitTodoRequest(BaseModel):
    share_id: str


def _raise(exc: TodoShareError) -> None:
    raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except TodoShareError as exc:
        _raise(exc)


def _agent_home() -> Path:
    return Path(os.environ.get("Y_AGENT_HOME", str(Path.home()))).resolve()


def _validate_content_key(content_key: str) -> None:
    home = _agent_home()
    path = (home / content_key).resolve()
    if home != path and home not in path.parents:
        raise HTTPException(status_code=422, detail="Note content not found")


async def _read_note_bytes(user_id: int, content_key: str) -> bytes:
    _validate_content_key(content_key)
    try:
        text = await run_vm_command(user_id, ["cat", content_key], timeout=30)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Note content not found") from exc
    body = text.encode("utf-8")
    if len(body) > NOTE_LIMIT:
        raise HTTPException(status_code=422, detail="Note content exceeds 1 MB")
    return body


def _put_snapshot(key: str, body: bytes) -> None:
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="Y_AGENT_S3_BUCKET is not configured")
    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=seal_body(key, body),
        ContentType="text/markdown",
    )


def _delete_snapshot(key: str) -> None:
    if not key or not S3_BUCKET:
        return
    try:
        boto3.client("s3").delete_object(Bucket=S3_BUCKET, Key=key)
    except ClientError:
        pass


def _read_snapshot(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="Y_AGENT_S3_BUCKET is not configured")
    try:
        obj = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=key)
        return open_body(key, obj["Body"].read()).decode("utf-8")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise HTTPException(status_code=503, detail="Note snapshot is temporarily unavailable") from exc


def _text(content) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _project_messages(messages) -> List[dict]:
    projected = []
    for message in messages or []:
        data = message.to_dict() if hasattr(message, "to_dict") else dict(message)
        role = data.get("role") or ""
        projected.append({
            "role": role,
            "content": "" if role == "tool" else _text(data.get("content")),
        })
    return projected


@router.post("/share")
async def create_share(req: ShareTodoRequest, request: Request):
    user_id = _get_user_id(request)
    prepared = _run(
        share_service.prepare_share,
        user_id,
        req.todo_id,
        req.to,
        req.notes,
        req.chats,
        req.links,
        req.clear_items,
    )
    bodies = {}
    for item in prepared["items"]:
        if item["kind"] == "note":
            bodies[item["ref_id"]] = await _read_note_bytes(user_id, item["content_key"])
    keyed = _run(share_service.snapshot_items, user_id, prepared["share_id"], prepared["items"])
    for item in keyed:
        if item["kind"] == "note":
            _put_snapshot(item["snapshot_key"], bodies[item["ref_id"]])
    saved = _run(
        share_service.save_share,
        user_id,
        prepared["recipient_id"],
        prepared["todo_id"],
        prepared["share_id"],
        keyed,
    )
    for key in saved["obsolete_keys"]:
        _delete_snapshot(key)
    notified = share_service.notify_share(
        prepared["recipient_id"], prepared["owner_label"], prepared["todo_name"],
    )
    return {
        "share_id": saved["share_id"],
        "notified": notified,
        "items": [{"kind": item["kind"], "ref_id": item["ref_id"]} for item in saved["items"]],
    }


@router.delete("/share")
async def delete_share(request: Request, todo_id: str = Query(...), to: str = Query(...)):
    user_id = _get_user_id(request)
    revoked = _run(share_service.revoke_share, user_id, todo_id, to)
    for key in revoked["snapshot_keys"]:
        _delete_snapshot(key)
    return {"ok": True}


@router.get("/shares")
async def list_shares(request: Request):
    return _run(share_service.list_outgoing, _get_user_id(request))


@router.get("/shared")
async def list_shared(request: Request):
    return _run(share_service.list_shared, _get_user_id(request))


@router.get("/shared/detail")
async def shared_detail(request: Request, share_id: str = Query(...)):
    user_id = _get_user_id(request)
    meta = _run(share_service.shared_detail, user_id, share_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Share not found")
    owner_id = meta["owner_id"]
    items = meta["items"]
    note_ids = [item["ref_id"] for item in items if item["kind"] == "note"]
    notes_by_id = {note.note_id: note for note in note_repo.get_notes_by_ids(owner_id, note_ids)}
    notes = []
    for item in items:
        if item["kind"] != "note":
            continue
        note = notes_by_id.get(item["ref_id"])
        notes.append({
            "note_id": item["ref_id"],
            "title": note_title(note) if note else item["ref_id"],
            "content": _read_snapshot(item.get("snapshot_key")),
        })
    chat_ids = [item["ref_id"] for item in items if item["kind"] == "chat"]
    titles = get_chat_metas(owner_id, chat_ids)
    chats = []
    for chat_id in chat_ids:
        chat = await get_chat(owner_id, chat_id)
        if chat is None or (chat.trace_id or "") != meta["todo_id"]:
            continue
        chats.append({
            "chat_id": chat_id,
            "title": titles.get(chat_id) or "",
            "messages": _project_messages(chat.messages),
        })
    link_ids = [item["ref_id"] for item in items if item["kind"] == "link"]
    activities = {row.activity_id: row for row in link_repo.get_links_by_activity_ids(owner_id, link_ids)}
    links = []
    for activity_id in link_ids:
        activity = activities.get(activity_id)
        if activity is None:
            continue
        content, _content_status = await _read_link_content(owner_id, activity.content_key)
        summary, _summary_status = await _read_link_content(owner_id, activity.summary_content_key)
        links.append({
            "activity_id": activity.activity_id,
            "link_id": activity.link_id,
            "title": activity.title or "",
            "url": activity.url or "",
            "summary": summary,
            "content": content,
        })
    return {"todo": meta["todo"], "notes": notes, "chats": chats, "links": links}


@router.get("/share/summary")
async def share_summary(request: Request):
    return _run(share_service.summary, _get_user_id(request))


@router.post("/visit")
async def visit_share(req: VisitTodoRequest, request: Request):
    return _run(share_service.record_visit, _get_user_id(request), req.share_id)


@router.get("/public")
async def list_public(request: Request):
    return _run(share_service.list_public, _get_user_id(request))
