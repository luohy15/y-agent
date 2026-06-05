import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.repository.chat import find_chats_by_trace_id, find_chats_with_messages_by_trace_id
from storage.util import generate_id

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _extract_segments(messages: list) -> List[dict]:
    """Extract time segments from messages.

    Each round (user message + its assistant/tool replies) is one segment.
    """
    rounds = []  # list of [start_ts, end_ts]

    for m in messages:
        role = m.get("role", "")
        ts = m.get("unix_timestamp", 0)
        if not ts:
            continue

        if role == "user":
            rounds.append([ts, ts])
        elif rounds:
            rounds[-1][1] = ts

    return [{"start_unix": start_ts, "end_unix": end_ts} for start_ts, end_ts in rounds]


@router.get("/list")
async def list_traces(request: Request, trace_id: str = Query(None), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """List distinct trace_ids from chats, ordered by most recent. Includes todo name."""
    user_id = _get_user_id(request)
    from storage.repository.chat import list_trace_ids
    traces = list_trace_ids(user_id, limit=limit, offset=offset, trace_id=trace_id)

    # Batch-lookup todo names for all trace_ids (trace_id = todo_id)
    trace_ids = [t["trace_id"] for t in traces]
    if trace_ids:
        from storage.repository.todo import find_todos_by_ids
        todo_map = find_todos_by_ids(user_id, trace_ids)
        for t in traces:
            todo = todo_map.get(t["trace_id"])
            t["todo_name"] = todo.name if todo else None
            t["todo_status"] = todo.status if todo else None

    return traces


@router.get("/latest_chat")
async def get_latest_chat(request: Request, trace_id: str = Query(...)):
    """Get the latest chat_id for a trace."""
    user_id = _get_user_id(request)
    chats = find_chats_by_trace_id(user_id, trace_id)
    if not chats:
        return {"chat_id": None}
    return {"chat_id": chats[0].chat_id}


@router.get("/chats")
async def get_trace_chats(request: Request, trace_id: str = Query(...)):
    """Get all chats participating in a trace, with message-derived time segments and todo info."""
    user_id = _get_user_id(request)
    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, skill, backend, bot_name, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "skill": skill,
            "backend": backend,
            "bot_name": bot_name,
            "segments": segments,
            "messages": messages,
        })

    # Lookup todo info (trace_id = todo_id)
    todo_info = None
    from storage.repository.todo import find_todos_by_ids
    todo_map = find_todos_by_ids(user_id, [trace_id])
    todo = todo_map.get(trace_id)
    if todo:
        todo_info = {
            "todo_id": todo.todo_id,
            "name": todo.name,
            "status": todo.status,
            "desc": todo.desc,
            "tags": todo.tags,
            "priority": todo.priority,
            "due_date": todo.due_date,
            "progress": todo.progress,
            "completed_at": todo.completed_at,
            "created_at": todo.created_at,
            "updated_at": todo.updated_at,
            "history": [
                {"timestamp": h.timestamp, "action": h.action, "note": h.note}
                for h in (todo.history or [])
            ],
        }

    # Fetch associated links
    from storage.repository.link_todo_relation import list_by_todo as list_link_relations
    from storage.repository.link import get_links_with_latest_activity
    link_ids = list_link_relations(user_id, trace_id)
    links = get_links_with_latest_activity(user_id, link_ids) if link_ids else []

    # Fetch associated notes
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note import get_notes_by_ids
    from storage.repository.note_share import get_by_note_ids as get_note_shares_by_note_ids
    note_ids = list_note_relations(user_id, trace_id)
    note_shares = {
        share.note_id: {
            "share_id": share.share_id,
            "has_password": bool(share.password_hash),
        }
        for share in get_note_shares_by_note_ids(user_id, note_ids)
    } if note_ids else {}
    notes = []
    if note_ids:
        for note in get_notes_by_ids(user_id, note_ids):
            note_data = note.to_dict()
            share = note_shares.get(note.note_id)
            if share:
                note_data.update(share)
            notes.append(note_data)

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
        "links": links,
        "notes": notes,
    }


def _strip_tool_results(messages: list) -> list:
    """Strip tool result content from messages to avoid leaking sensitive data."""
    stripped = []
    for m in messages:
        msg = dict(m)
        if msg.get("role") == "tool":
            msg["content"] = ""
        stripped.append(msg)
    return stripped


class CreateShareRequest(BaseModel):
    trace_id: str
    password: Optional[str] = None
    generate_password: bool = False
    note_ids: Optional[List[str]] = None


@router.post("/share")
async def create_share(req: CreateShareRequest, request: Request):
    """Create a shareable link for a trace, optionally batch-sharing assoc'd notes.

    When ``note_ids`` is supplied, each note is shared server-side in public mode
    (no password) best-effort, and the response gains a ``notes`` list. Omitting
    ``note_ids`` keeps the original ``{share_id, password?}`` shape (back-compat).
    """
    from storage import share_password as sp
    from storage.repository.trace_share import get_by_trace_id, create, set_password_hash, set_revoked

    user_id = _get_user_id(request)

    generated_password: Optional[str] = None
    password_hash: Optional[str] = None
    if req.generate_password and not (req.password and req.password.strip()):
        generated_password = sp.generate_password()
        password_hash = sp.hash_password(generated_password)
    elif req.password and req.password.strip():
        password_hash = sp.hash_password(req.password)

    existing = get_by_trace_id(user_id, req.trace_id, include_revoked=True)
    if existing:
        if existing.revoked_at is not None:
            set_revoked(existing.share_id, None)
        if password_hash is not None:
            set_password_hash(existing.share_id, password_hash)
        share_id = existing.share_id
    else:
        share_id = generate_id()
        create(user_id, share_id, req.trace_id, password_hash=password_hash)

    resp = {"share_id": share_id}
    if generated_password is not None:
        resp["password"] = generated_password

    if req.note_ids is not None:
        # Share notes in public mode (no password): the public trace page renders
        # note links as bare /n/<share_id>, so a per-note password would force a
        # second prompt there. Best-effort: skip per-note failures.
        from api.controller.note import share_note
        shared_notes = []
        for note_id in req.note_ids:
            try:
                note_resp = await share_note(user_id, note_id)
            except Exception:
                continue
            shared_notes.append({"note_id": note_id, "share_id": note_resp["share_id"]})
        resp["notes"] = shared_notes

    return resp


@router.delete("/share")
async def delete_share(request: Request, share_id: str = Query(...)):
    """Delete a share link owned by the current user.

    Cascade: also revoke shares for every note associated with this trace's todo,
    so the public ``/n/<share_id>`` note links never outlive the trace share
    (authoritative mirror of ``create_share``'s batch note-share). Done server-side
    rather than in the frontend so unshare is robust regardless of what notes the
    web client currently has loaded.
    """
    from storage.repository.trace_share import get_by_share_id, set_revoked
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note_share import get_by_note_ids
    from storage.util import get_utc_iso8601_timestamp
    from api.controller.note import revoke_note_share

    user_id = _get_user_id(request)
    share = get_by_share_id(share_id)
    if not share or share.user_id != user_id:
        raise HTTPException(status_code=404, detail="Share not found")
    set_revoked(share_id, get_utc_iso8601_timestamp())

    note_ids = list_note_relations(user_id, share.trace_id)
    if note_ids:
        for note_share in get_by_note_ids(user_id, note_ids):
            revoke_note_share(note_share)

    return {"deleted": True}


@router.get("/share/mine")
async def get_my_share(request: Request, trace_id: str = Query(...)):
    """Get the current user's share for a trace, if any."""
    from storage.repository.trace_share import get_by_trace_id

    user_id = _get_user_id(request)
    share = get_by_trace_id(user_id, trace_id)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    return {
        "share_id": share.share_id,
        "trace_id": share.trace_id,
        "has_password": bool(share.password_hash),
    }


@router.get("/shares")
async def list_shares(request: Request):
    """List all shares owned by the current user."""
    from storage.repository.trace_share import list_by_user

    user_id = _get_user_id(request)
    shares = list_by_user(user_id)
    return [
        {
            "share_id": s.share_id,
            "trace_id": s.trace_id,
            "has_password": bool(s.password_hash),
        }
        for s in shares
    ]


@router.get("/share")
async def get_share(share_id: str = Query(...), password: Optional[str] = Query(None)):
    """Public endpoint: get trace data by share_id."""
    from storage.repository.trace_share import get_by_share_id
    from storage import share_password as sp

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

    user_id = share.user_id
    trace_id = share.trace_id

    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, skill, backend, bot_name, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "skill": skill,
            "backend": backend,
            "bot_name": bot_name,
            "segments": segments,
            "messages": _strip_tool_results(messages),
        })

    # Lookup todo info
    todo_info = None
    from storage.repository.todo import find_todos_by_ids
    todo_map = find_todos_by_ids(user_id, [trace_id])
    todo = todo_map.get(trace_id)
    if todo:
        todo_info = {
            "todo_id": todo.todo_id,
            "name": todo.name,
            "status": todo.status,
            "desc": todo.desc,
            "tags": todo.tags,
            "priority": todo.priority,
            "due_date": todo.due_date,
            "progress": todo.progress,
            "completed_at": todo.completed_at,
            "created_at": todo.created_at,
            "updated_at": todo.updated_at,
            "history": [
                {"timestamp": h.timestamp, "action": h.action, "note": h.note}
                for h in (todo.history or [])
            ],
        }

    # Fetch associated links
    from storage.repository.link_todo_relation import list_by_todo as list_link_relations
    from storage.repository.link import get_links_with_latest_activity
    link_ids = list_link_relations(user_id, trace_id)
    links = get_links_with_latest_activity(user_id, link_ids) if link_ids else []

    # Fetch associated notes
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note import get_notes_by_ids
    from storage.repository.note_share import get_by_note_ids as get_note_shares_by_note_ids
    note_ids = list_note_relations(user_id, trace_id)
    note_shares = {
        share.note_id: {
            "share_id": share.share_id,
            "has_password": bool(share.password_hash),
        }
        for share in get_note_shares_by_note_ids(user_id, note_ids)
    } if note_ids else {}
    notes = []
    if note_ids:
        for note in get_notes_by_ids(user_id, note_ids):
            note_data = note.to_dict()
            share = note_shares.get(note.note_id)
            if share:
                note_data.update(share)
            notes.append(note_data)

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
        "links": links,
        "notes": notes,
    }
