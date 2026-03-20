import json
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request

from storage.repository.chat import find_chats_by_trace_id, find_chats_with_messages_by_trace_id

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _extract_segments(messages: list, trace_id: str) -> List[dict]:
    """Extract time segments from messages belonging to this trace.

    A segment starts when a user message with matching trace_id appears,
    and extends through subsequent messages until the next user message
    (which may start a new segment or end the current one).
    Returns list of {start_unix, end_unix}.
    """
    # Assign effective trace_id: user messages carry it explicitly,
    # subsequent non-user messages inherit from the last user message
    current_trace = None
    annotated = []  # (unix_timestamp, belongs_to_trace)
    for m in messages:
        role = m.get("role", "")
        msg_trace = m.get("trace_id")
        ts = m.get("unix_timestamp", 0)
        if not ts:
            continue

        if role == "user" and msg_trace:
            current_trace = msg_trace
        belongs = (current_trace == trace_id)
        annotated.append((ts, belongs))

    # Build segments from consecutive belongs=True runs
    segments: List[dict] = []
    seg_start = None
    seg_end = None
    for ts, belongs in annotated:
        if belongs:
            if seg_start is None:
                seg_start = ts
            seg_end = ts
        else:
            if seg_start is not None:
                segments.append({"start_unix": seg_start, "end_unix": seg_end})
                seg_start = None
                seg_end = None
    if seg_start is not None:
        segments.append({"start_unix": seg_start, "end_unix": seg_end})

    return segments


@router.get("/list")
async def list_traces(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """List distinct trace_ids from chats, ordered by most recent. Includes todo name."""
    user_id = _get_user_id(request)
    from storage.repository.chat import list_trace_ids
    traces = list_trace_ids(user_id, limit=limit, offset=offset)

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


@router.get("/chats")
async def get_trace_chats(request: Request, trace_id: str = Query(...)):
    """Get all chats participating in a trace, with message-derived time segments."""
    user_id = _get_user_id(request)
    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result = []
    for chat_id, title, skill, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages, trace_id)
        result.append({
            "chat_id": chat_id,
            "title": title,
            "skill": skill,
            "segments": segments,
        })
    return result


@router.get("/by-chat")
async def get_trace_by_chat(request: Request, chat_id: str = Query(...)):
    """Find the active trace for a chat."""
    user_id = _get_user_id(request)
    from storage.repository.chat import get_chat
    chat = await get_chat(user_id, chat_id)
    if not chat or not chat.active_trace_id:
        raise HTTPException(status_code=404, detail="trace not found for chat_id")
    return {"trace_id": chat.active_trace_id, "skill": chat.skill}
