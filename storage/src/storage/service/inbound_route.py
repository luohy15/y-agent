"""Shared `/<todo_id>` inbound route resolution for every gateway channel."""

from typing import Optional, Tuple

from storage.dto.chat import Chat
from storage.repository import chat as chat_repo
from storage.repository import todo as todo_repo
from storage.repository import todo_share as todo_share_repo
from storage.todo_sla import OPEN_STATUSES


def usage_notice(todo_id: str) -> str:
    return f"Usage: /{todo_id} <message>"


async def resolve_todo_route(user_id: int, todo_id: str) -> Tuple[Optional[Chat], Optional[str]]:
    """Resolve an inbound `/<todo_id>` prefix to the todo owner's chat.

    Returns `(chat, None)` for an open todo that has a trace chat, else
    `(None, notice)`. Prefers the todo's handle chat when it still belongs to
    the todo's trace, then the latest chat of that trace. Never creates a
    chat. A todo the caller does not own gets a read-only share notice when a
    live grant exists, otherwise not-found.
    """
    handle_chat, status = todo_repo.find_handle_state(user_id, todo_id)
    if handle_chat is None and status is None:
        if todo_share_repo.find_live_incoming(user_id, todo_id):
            return None, f"todo /{todo_id} is shared read-only"
        return None, f"todo /{todo_id} not found"
    if status not in OPEN_STATUSES:
        return None, f"todo /{todo_id} is closed"
    target = None
    if handle_chat:
        candidate = await chat_repo.get_chat(user_id, handle_chat)
        if candidate is not None and candidate.trace_id == todo_id:
            target = candidate
    if target is None:
        target = chat_repo.find_latest_chat_by_trace_id(user_id, todo_id)
    if target is None:
        return None, f"no chat for todo /{todo_id}"
    return target, None
