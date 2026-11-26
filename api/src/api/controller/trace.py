import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.repository.chat import find_chats_by_trace_id, find_chats_with_messages_by_trace_id
from storage.role import COORDINATOR_ROLE
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


@router.get("/usage")
async def get_trace_usage(request: Request, trace_id: str = Query(...)):
    """Per-trace usage: chats, turns, requests and token counters (todo 3729).

    Cost is reported unavailable and historical completeness is always unknown.
    A trace with no chats returns zeros rather than 404, so a fresh todo and a
    todo with no recorded usage read the same way.
    """
    from storage.service import chat_request_usage as request_usage_service

    return request_usage_service.aggregate_for_trace(_get_user_id(request), trace_id)


def _associated_links(user_id: int, trace_id: str) -> list:
    """Resolve a todo's link relations by activity id, newest activity first.

    ``link_todo_relation`` stores ``activity_id``. Orphan rows whose activity
    was deleted do not resolve and are omitted.
    """
    from storage.repository.link import get_links_by_activity_ids
    from storage.repository.link_todo_relation import list_by_todo as list_link_relations

    activity_ids = list_link_relations(user_id, trace_id)
    if not activity_ids:
        return []
    links = [row.to_dict() for row in get_links_by_activity_ids(user_id, activity_ids)]
    links.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return links


def preferred_trace_chat(chats):
    """Newest coordinator chat, or the newest chat overall.

    ``chats`` is already newest-first. ``leader`` wins over an older ``dev``
    chat because it appears first; a trace that only has ``dev`` still resolves
    to that chat.
    """
    if not chats:
        return None
    coordinator = next((chat for chat in chats if chat.role == COORDINATOR_ROLE), None)
    return coordinator or chats[0]


def resolve_open_chat(chats, handle, todo_status):
    """Prefer the handle only while it names a live chat on this trace.

    The handle is the source of truth for who owns the conversation, but an
    idle, non-attention chat cannot answer anymore. Opening such a todo must
    land on a chat that can, so an ended handle falls back to the newest
    coordinator chat, then the newest chat. An awaiting todo always opens its
    handle: entering awaiting is itself the pointer write.
    """
    if handle:
        held = next((chat for chat in chats if chat.chat_id == handle), None)
        if held is not None and (
            todo_status == "awaiting" or held.status == "running" or held.needs_attention
        ):
            return held
    return preferred_trace_chat(chats)


@router.get("/latest_chat")
async def get_latest_chat(request: Request, trace_id: str = Query(...)):
    """Open the trace's held chat, falling back to coordinator/newest."""
    from storage.service.todo import find_handle_state

    user_id = _get_user_id(request)
    chats = find_chats_by_trace_id(user_id, trace_id)
    handle, status = find_handle_state(user_id, trace_id)
    chosen = resolve_open_chat(chats, handle, status)
    return {"chat_id": chosen.chat_id if chosen is not None else None}


@router.get("/chats")
async def get_trace_chats(request: Request, trace_id: str = Query(...)):
    """Get all chats participating in a trace, with message-derived time segments and todo info."""
    user_id = _get_user_id(request)
    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, role, skill, backend, bot_name, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        # Message bodies are served by the chat module. This authenticated
        # payload keeps only message-derived segments; get_share retains bodies
        # (tool results stripped) for the public projection.
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "role": role,
            "skill": skill,
            "backend": backend,
            "bot_name": bot_name,
            "segments": segments,
        })

    # Lookup todo info (trace_id = todo_id)
    todo_info = None
    from storage.repository.todo import find_todos_by_ids
    todo_map = find_todos_by_ids(user_id, [trace_id])
    todo = todo_map.get(trace_id)
    if todo:
        from storage.service.todo import attach_next_wakeup, attach_pending_release_waiter
        attach_next_wakeup(user_id, [todo])
        attach_pending_release_waiter(user_id, [todo])
        open_chat = resolve_open_chat(
            find_chats_by_trace_id(user_id, trace_id), todo.handle_chat, todo.status)
        todo_info = {
            "todo_id": todo.todo_id,
            "name": todo.name,
            "status": todo.status,
            "desc": todo.desc,
            "tags": todo.tags,
            "priority": todo.priority,
            "due_date": todo.due_date,
            "progress": todo.progress,
            "handle_chat": todo.handle_chat,
            "open_chat": open_chat.chat_id if open_chat is not None else None,
            "next_wakeup_at_unix": todo.next_wakeup_at_unix,
            "has_pending_release_waiter": todo.has_pending_release_waiter,
            "completed_at": todo.completed_at,
            "created_at": todo.created_at,
            "updated_at": todo.updated_at,
            "history": [
                {"timestamp": h.timestamp, "action": h.action, "note": h.note}
                for h in reversed(todo.history or [])
            ],
        }

    links = _associated_links(user_id, trace_id)

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

    # Fetch associated calendar events (calendar_event.todo_id = trace_id)
    from storage.repository.calendar_event import list_events as list_calendar_events
    calendar_events = [e.to_dict() for e in list_calendar_events(user_id, todo_id=trace_id)]

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
        "links": links,
        "notes": notes,
        "calendar_events": calendar_events,
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
    chat_ids: Optional[List[str]] = None
    link_ids: Optional[List[str]] = None


def _public_password_gate(share, password: Optional[str]) -> None:
    """Password + rate-limit gate shared by the public payload and note reads."""
    from storage import share_password as sp

    if not share.password_hash:
        return
    if not password:
        raise HTTPException(status_code=401, detail={"password_required": True})
    allowed, retry_after = sp.check_rate_limit(share.share_id)
    if not allowed:
        raise HTTPException(status_code=429, detail={"retry_after": retry_after})
    if not sp.verify_password(password, share.password_hash):
        sp.record_failure(share.share_id)
        raise HTTPException(status_code=403, detail="Invalid password")


def _live_public_share(share_id: str):
    from storage.repository.todo_share import get_public_by_share_id

    share = get_public_by_share_id(share_id)
    if not share or share.revoked_at:
        raise HTTPException(status_code=404, detail="Share not found")
    return share


def _live_public_todo(share):
    from storage.repository.todo import get_todo

    todo = get_todo(share.user_id, share.todo_id)
    if todo is None or todo.status == "deleted":
        raise HTTPException(status_code=404, detail="Share not found")
    return todo


@router.post("/share")
async def create_share(req: CreateShareRequest, request: Request):
    """Create or update a trace's public share.

    A request carrying at least one selection list is a closed item allowlist
    (``selection_mode=items``); no lists keeps the legacy dynamic ``all``
    share. Selected note bodies are written as sealed per-share snapshots.
    """
    from api.controller.todo_share import _read_note_bytes
    from api.share_snapshot import delete_snapshot, put_snapshot
    from storage import share_password as sp
    from storage.repository.todo import get_todo
    from storage.repository.todo_share import get_public_by_trace_id, save_public
    from storage.service.todo_share import (
        TodoShareError,
        prepare_public_selection,
        snapshot_items,
    )

    user_id = _get_user_id(request)
    todo = get_todo(user_id, req.trace_id)
    if todo is None or todo.status == "deleted":
        raise HTTPException(status_code=404, detail="Todo not found")
    try:
        prepared = prepare_public_selection(
            user_id, todo.todo_id, req.note_ids, req.chat_ids, req.link_ids,
        )
    except TodoShareError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    bodies = {}
    for item in prepared["items"]:
        if item["kind"] == "note":
            bodies[item["ref_id"]] = await _read_note_bytes(user_id, item["content_key"])

    generated_password: Optional[str] = None
    password_hash: Optional[str] = None
    if req.generate_password and not (req.password and req.password.strip()):
        generated_password = sp.generate_password()
        password_hash = sp.hash_password(generated_password)
    elif req.password and req.password.strip():
        password_hash = sp.hash_password(req.password)

    existing = get_public_by_trace_id(user_id, todo.todo_id, include_revoked=True)
    share_id = existing.share_id if existing else generate_id()
    keyed = snapshot_items(user_id, share_id, prepared["items"])
    for item in keyed:
        if item["kind"] == "note":
            put_snapshot(item["snapshot_key"], bodies[item["ref_id"]])
    saved = save_public(
        user_id,
        share_id,
        todo.todo_id,
        prepared["selection_mode"],
        keyed,
        password_hash=password_hash,
        replace_password=password_hash is not None or req.password == "",
    )
    for key in saved["obsolete_keys"]:
        delete_snapshot(key)

    resp = {"share_id": saved["share_id"]}
    if generated_password is not None:
        resp["password"] = generated_password
    return resp


@router.delete("/share")
async def delete_share(request: Request, share_id: str = Query(...)):
    """Revoke a public share.

    Deletes its item snapshots and revokes any related ``note_share`` rows for
    the selected notes (``all`` covers every related note), so legacy
    ``/n/<share_id>`` links never outlive the trace share.
    """
    from api.controller.note import revoke_note_share
    from api.share_snapshot import delete_snapshot
    from storage.repository.note_share import get_by_note_ids
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.todo_share import (
        get_public_by_share_id,
        list_items,
        revoke_public,
    )

    user_id = _get_user_id(request)
    share = get_public_by_share_id(share_id)
    if not share or share.user_id != user_id:
        raise HTTPException(status_code=404, detail="Share not found")
    items = list_items(share_id)
    for key in revoke_public(share_id) or []:
        delete_snapshot(key)

    if (share.selection_mode or "all") == "all":
        note_ids = list_note_relations(user_id, share.todo_id)
    else:
        note_ids = [item["ref_id"] for item in items if item["kind"] == "note"]
    for note_share in get_by_note_ids(user_id, note_ids):
        revoke_note_share(note_share)

    return {"deleted": True}


@router.get("/share/mine")
async def get_my_share(request: Request, trace_id: str = Query(...)):
    """Get the current user's public share for a trace, if any."""
    from storage.repository.todo_share import get_public_by_trace_id
    from storage.service.todo_share import selection_payload

    user_id = _get_user_id(request)
    share = get_public_by_trace_id(user_id, trace_id)
    # Empty is a normal result. 404 shows up as a browser console network error
    # even when the client treats it as "no share".
    if not share:
        return None
    return {
        "share_id": share.share_id,
        "trace_id": share.todo_id,
        "has_password": bool(share.password_hash),
        "selection": selection_payload(share),
    }


@router.get("/shares")
async def list_shares(request: Request):
    """List all shares owned by the current user."""
    from storage.repository.todo_share import list_public_by_user

    user_id = _get_user_id(request)
    shares = list_public_by_user(user_id)
    return [
        {
            "share_id": s.share_id,
            "trace_id": s.todo_id,
            "has_password": bool(s.password_hash),
        }
        for s in shares
    ]


@router.get("/share")
async def get_share(share_id: str = Query(...), password: Optional[str] = Query(None)):
    """Public endpoint: get trace data by share_id."""
    from storage.repository.note import get_notes_by_ids
    from storage.repository.note_share import get_by_note_ids
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.todo_share import list_items
    from storage.service.todo_share import public_selected

    share = _live_public_share(share_id)
    _public_password_gate(share, password)
    todo = _live_public_todo(share)
    user_id = share.user_id
    trace_id = todo.todo_id
    selected = public_selected(share)
    item_keys = {
        item["ref_id"]: item["snapshot_key"]
        for item in list_items(share.share_id)
        if item["kind"] == "note"
    }

    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, role, skill, backend, bot_name, json_content in chats:
        if selected is not None and chat_id not in selected["chat"]:
            continue
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "role": role,
            "skill": skill,
            "backend": backend,
            "bot_name": bot_name,
            "segments": segments,
            "messages": _strip_tool_results(messages),
        })

    # Lookup todo info
    todo_info = {
        "todo_id": todo.todo_id,
        "name": todo.name,
        "status": todo.status,
        "desc": todo.desc,
        "tags": todo.tags,
        "priority": todo.priority,
        "due_date": todo.due_date,
        "progress": todo.progress,
        "handle_chat": todo.handle_chat,
        "completed_at": todo.completed_at,
        "created_at": todo.created_at,
        "updated_at": todo.updated_at,
        "history": [
            {"timestamp": h.timestamp, "action": h.action, "note": h.note}
            for h in reversed(todo.history or [])
        ],
    }

    links = _associated_links(user_id, trace_id)
    if selected is not None:
        links = [link for link in links if link["activity_id"] in selected["link"]]

    # Related notes: bodies live in the item snapshot (or a legacy note_share
    # snapshot, which `/share/note` still falls back to).
    note_ids = list_note_relations(user_id, trace_id)
    if selected is not None:
        note_ids = [note_id for note_id in note_ids if note_id in selected["note"]]
    legacy_note_shares = (
        {share.note_id for share in get_by_note_ids(user_id, note_ids) if not share.password_hash}
        if note_ids else set()
    )
    notes = []
    if note_ids:
        for note in get_notes_by_ids(user_id, note_ids):
            note_data = note.to_dict()
            note_data["openable"] = bool(item_keys.get(note.note_id)) or note.note_id in legacy_note_shares
            notes.append(note_data)

    # Fetch associated calendar events (calendar_event.todo_id = trace_id)
    from storage.repository.calendar_event import list_events as list_calendar_events
    calendar_events = [e.to_dict() for e in list_calendar_events(user_id, todo_id=trace_id)]

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
        "links": links,
        "notes": notes,
        "calendar_events": calendar_events,
    }


@router.get("/share/note")
async def get_share_note(
    share_id: str = Query(...),
    note_id: str = Query(...),
    password: Optional[str] = Query(None),
):
    """Public endpoint: one shared note's sealed body.

    Serves the selected item snapshot; a migrated legacy item without a key
    falls back to the note's live ``note_share`` snapshot.
    """
    from api.share_snapshot import read_snapshot
    from storage.repository.note import get_note
    from storage.repository.note_share import get_by_note_id
    from storage.repository.todo_share import list_items
    from storage.service.todo_share import related_ids

    share = _live_public_share(share_id)
    _public_password_gate(share, password)
    todo = _live_public_todo(share)
    user_id = share.user_id

    key = None
    if (share.selection_mode or "all") == "items":
        item = next(
            (row for row in list_items(share.share_id)
             if row["kind"] == "note" and row["ref_id"] == note_id),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Note not found")
        key = item.get("snapshot_key")
    elif note_id not in related_ids(user_id, todo.todo_id)["note"]:
        raise HTTPException(status_code=404, detail="Note not found")

    note = get_note(user_id, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    content = read_snapshot(key)
    if content is None:
        # Migrated legacy item: reuse the note's own snapshot (new key or the
        # pre-change object). A password-protected standalone note share was
        # never readable here, so it is not advertised or served either.
        from api.controller.note import _share_snapshot_key

        legacy = get_by_note_id(user_id, note_id)
        if legacy is None or legacy.password_hash:
            raise HTTPException(status_code=404, detail="Note content not found")
        content = read_snapshot(_share_snapshot_key(legacy))
        if content is None:
            raise HTTPException(status_code=404, detail="Note content not found")

    data = note.to_dict()
    data["content"] = content
    return data
