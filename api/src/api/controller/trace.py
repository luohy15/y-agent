import json
from typing import List

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
    for chat_id, title, topic, backend, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "backend": backend,
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
    note_ids = list_note_relations(user_id, trace_id)
    notes = [n.to_dict() for n in get_notes_by_ids(user_id, note_ids)] if note_ids else []

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


@router.post("/share")
async def create_share(req: CreateShareRequest, request: Request):
    """Create a shareable link for a trace."""
    user_id = _get_user_id(request)
    from storage.repository.trace_share import get_by_trace_id, create
    existing = get_by_trace_id(user_id, req.trace_id)
    if existing:
        return {"share_id": existing.share_id}
    share_id = generate_id()
    create(user_id, share_id, req.trace_id)
    return {"share_id": share_id}


@router.get("/share")
async def get_share(share_id: str = Query(...)):
    """Public endpoint: get trace data by share_id."""
    from storage.repository.trace_share import get_by_share_id
    share = get_by_share_id(share_id)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    user_id = share.user_id
    trace_id = share.trace_id

    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, topic, backend, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "topic": topic,
            "backend": backend,
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
    note_ids = list_note_relations(user_id, trace_id)
    notes = [n.to_dict() for n in get_notes_by_ids(user_id, note_ids)] if note_ids else []

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
        "links": links,
        "notes": notes,
    }
