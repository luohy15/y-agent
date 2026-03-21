import json
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request

from storage.repository.chat import find_chats_by_trace_id, find_chats_with_messages_by_trace_id

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _annotate_trace_belonging(messages: list, trace_id: str) -> List[bool]:
    """Annotate each message with whether it belongs to this trace.

    Returns a list of booleans parallel to messages (skipping messages without timestamps).
    """
    current_trace = None
    belongs_list = []
    for m in messages:
        role = m.get("role", "")
        msg_trace = m.get("trace_id")
        ts = m.get("unix_timestamp", 0)
        if not ts:
            belongs_list.append(False)
            continue

        if role == "user":
            current_trace = msg_trace
        belongs_list.append(current_trace == trace_id)

    return belongs_list


def _filter_messages_for_trace(messages: list, trace_id: str) -> list:
    """Filter messages to only those belonging to this trace."""
    belongs_list = _annotate_trace_belonging(messages, trace_id)
    # If no message-level match, return all messages (fallback)
    if not any(belongs_list):
        return messages
    return [m for m, b in zip(messages, belongs_list) if b]


def _extract_segments(messages: list, trace_id: str) -> List[dict]:
    """Extract time segments from messages belonging to this trace.

    A segment = user message (start) through last reply before next user message (end).
    Only user messages carry trace_id; assistant/tool messages inherit from the
    preceding user message.

    Fallback: if no user message has matching trace_id (e.g. dev-manager chat where
    trace_id was set at chat level, not message level), use first message → last message.
    """
    # Pass 1: annotate each message with whether it belongs to this trace
    current_trace = None
    annotated = []  # (unix_timestamp, belongs_to_trace)
    for m in messages:
        role = m.get("role", "")
        msg_trace = m.get("trace_id")
        ts = m.get("unix_timestamp", 0)
        if not ts:
            continue

        if role == "user":
            current_trace = msg_trace  # reset on every user message (None clears it)
        belongs = (current_trace == trace_id)
        annotated.append((ts, belongs))

    # Pass 2: build segments from consecutive belongs=True runs
    # Split into separate segments when gap between messages exceeds 5 minutes
    GAP_THRESHOLD_MS = 5 * 60 * 1000  # 5 minutes in milliseconds
    segments: List[dict] = []
    seg_start = None
    seg_end = None
    for ts, belongs in annotated:
        if belongs:
            if seg_start is None:
                seg_start = ts
                seg_end = ts
            elif ts - seg_end > GAP_THRESHOLD_MS:
                # Gap too large, close current segment and start a new one
                segments.append({"start_unix": seg_start, "end_unix": seg_end})
                seg_start = ts
                seg_end = ts
            else:
                seg_end = ts
        else:
            if seg_start is not None:
                segments.append({"start_unix": seg_start, "end_unix": seg_end})
                seg_start = None
                seg_end = None
    if seg_start is not None:
        segments.append({"start_unix": seg_start, "end_unix": seg_end})

    # Fallback: no message-level match, use all messages but still split by time gaps
    if not segments and annotated:
        seg_start = annotated[0][0]
        seg_end = annotated[0][0]
        for ts, _ in annotated[1:]:
            if ts - seg_end > GAP_THRESHOLD_MS:
                segments.append({"start_unix": seg_start, "end_unix": seg_end})
                seg_start = ts
                seg_end = ts
            else:
                seg_end = ts
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
    """Get all chats participating in a trace, with message-derived time segments and todo info."""
    user_id = _get_user_id(request)
    chats = find_chats_with_messages_by_trace_id(user_id, trace_id)
    result_chats = []
    for chat_id, title, skill, json_content in chats:
        messages = json.loads(json_content).get("messages", []) if json_content else []
        segments = _extract_segments(messages, trace_id)
        trace_messages = _filter_messages_for_trace(messages, trace_id)
        result_chats.append({
            "chat_id": chat_id,
            "title": title,
            "skill": skill,
            "segments": segments,
            "messages": trace_messages,
        })

    # Lookup todo info (trace_id = todo_id)
    todo_name = None
    todo_status = None
    from storage.repository.todo import find_todos_by_ids
    todo_map = find_todos_by_ids(user_id, [trace_id])
    todo = todo_map.get(trace_id)
    if todo:
        todo_name = todo.name
        todo_status = todo.status

    return {"chats": result_chats, "todo_name": todo_name, "todo_status": todo_status}


@router.get("/by-chat")
async def get_trace_by_chat(request: Request, chat_id: str = Query(...)):
    """Find the active trace for a chat."""
    user_id = _get_user_id(request)
    from storage.repository.chat import get_chat
    chat = await get_chat(user_id, chat_id)
    if not chat or not chat.active_trace_id:
        raise HTTPException(status_code=404, detail="trace not found for chat_id")
    return {"trace_id": chat.active_trace_id, "skill": chat.skill}
