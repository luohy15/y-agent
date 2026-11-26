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


def _public_selection(req, related):
    selection = {}
    for kind, ids in related.items():
        key = f"{kind}_ids"
        requested = getattr(req, key)
        if requested is not None:
            if not set(requested) <= ids:
                raise HTTPException(status_code=422, detail=f"Unknown or unrelated {kind}")
            selection[key] = list(dict.fromkeys(requested))
    return selection or None


@router.post("/share")
async def create_share(req: CreateShareRequest, request: Request):
    """Create a shareable link for a trace, optionally batch-sharing assoc'd notes.

    When ``note_ids`` is supplied, each note is shared server-side in public mode
    (no password) best-effort, and the response gains a ``notes`` list. Omitting
    ``note_ids`` keeps the original ``{share_id, password?}`` shape (back-compat).
    """
    from storage import share_password as sp
    from api.controller.note import revoke_note_share
    from storage.repository.note_share import get_by_note_ids
    from storage.repository.todo import get_todo
    from storage.repository.todo_share import create_public, get_public_by_trace_id, update_public_options
    from storage.service.todo_share import related_ids

    user_id = _get_user_id(request)
    todo = get_todo(user_id, req.trace_id)
    if todo is None or todo.status == "deleted":
        raise HTTPException(status_code=404, detail="Todo not found")
    trace_id = todo.todo_id
    related = related_ids(user_id, trace_id)
    selection = _public_selection(req, related)

    generated_password: Optional[str] = None
    password_hash: Optional[str] = None
    if req.generate_password and not (req.password and req.password.strip()):
        generated_password = sp.generate_password()
        password_hash = sp.hash_password(generated_password)
    elif req.password and req.password.strip():
        password_hash = sp.hash_password(req.password)

    existing = get_public_by_trace_id(user_id, trace_id, include_revoked=True)
    if existing:
        share_id = existing.share_id
        previous = (existing.selection or {}).get("note_ids", related["note"])
        if not existing.revoked_at and req.note_ids is not None:
            for note_share in get_by_note_ids(user_id, list(set(previous) - set(req.note_ids))):
                revoke_note_share(note_share)
        update_public_options(share_id, selection, password_hash, password_hash is not None or req.password == "")
    else:
        share_id = generate_id()
        create_public(user_id, share_id, trace_id, password_hash=password_hash, selection=selection)

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
    from storage.repository.todo_share import get_public_by_share_id, set_public_revoked
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note_share import get_by_note_ids
    from storage.util import get_utc_iso8601_timestamp
    from api.controller.note import revoke_note_share

    user_id = _get_user_id(request)
    share = get_public_by_share_id(share_id)
    if not share or share.user_id != user_id:
        raise HTTPException(status_code=404, detail="Share not found")
    set_public_revoked(share_id, get_utc_iso8601_timestamp())

    note_ids = (share.selection or {}).get("note_ids")
    if note_ids is None:
        note_ids = list_note_relations(user_id, share.todo_id)
    if note_ids:
        for note_share in get_by_note_ids(user_id, note_ids):
            revoke_note_share(note_share)

    return {"deleted": True}


@router.get("/share/mine")
async def get_my_share(request: Request, trace_id: str = Query(...)):
    """Get the current user's share for a trace, if any."""
    from storage.repository.todo_share import get_public_by_trace_id

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
        "selection": share.selection,
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
    from storage.repository.todo import get_todo
    from storage.repository.todo_share import get_public_by_share_id
    from storage import share_password as sp

    share = get_public_by_share_id(share_id)
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
    trace_id = share.todo_id
    todo = get_todo(user_id, trace_id)
    if todo is None or todo.status == "deleted":
        raise HTTPException(status_code=404, detail="Share not found")
    selection = share.selection or {}

    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, role, skill, backend, bot_name, json_content in chats:
        if "chat_ids" in selection and chat_id not in selection["chat_ids"]:
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
    if "link_ids" in selection:
        links = [link for link in links if link["activity_id"] in selection["link_ids"]]

    # Fetch associated notes
    from storage.repository.note_todo_relation import list_by_todo as list_note_relations
    from storage.repository.note import get_notes_by_ids
    from storage.repository.note_share import get_by_note_ids as get_note_shares_by_note_ids
    note_ids = list_note_relations(user_id, trace_id)
    if "note_ids" in selection:
        note_ids = [note_id for note_id in note_ids if note_id in selection["note_ids"]]
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
