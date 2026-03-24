import json
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request

from storage.repository.chat import find_chats_by_trace_id, find_chats_with_messages_by_trace_id

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


@router.get("/chats")
async def get_trace_chats(request: Request, trace_id: str = Query(...)):
    """Get all chats participating in a trace, with message-derived time segments and todo info."""
    user_id = _get_user_id(request)
    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, skill, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "skill": skill,
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
        }

    return {
        "chats": result_chats,
        "todo_name": todo.name if todo else None,
        "todo_status": todo.status if todo else None,
        "todo": todo_info,
    }
