"""Coordinator claim on the todo row (todo 4080).

Three nullable columns, written only here, under the todo row lock. A NULL
``leader_state`` still reads the latest ``[dev-claim]`` progress marker.
"""

import re
from typing import Optional, Tuple

from storage.dto.todo import Todo, TodoHistoryEntry
from storage.repository.todo import mutate_todo
from storage.service.todo import _transition_locked, get_latest_marker
from storage.util import get_utc_iso8601_timestamp

from storage.role import COORDINATOR_ROLE
from storage.repository.chat import effective_role_expr
MAX_HANDOFF = 1000
_CLAIM_RE = re.compile(r"\[dev-claim\] (CLAIM|RELEASE|TAKEOVER) chat=(\S+)")


class LeaderClaimError(Exception):
    def __init__(self, reason: str, owner: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.owner = owner


class LeaderClaimConflict(LeaderClaimError):
    """Another chat holds the claim (HTTP 409)."""


class LeaderClaimInvalid(LeaderClaimError):
    """The chat or payload cannot hold a claim (HTTP 422)."""


def _view(state: str, chat_id: Optional[str], claimed_at: Optional[str], source: str) -> dict:
    return {"state": state, "chat_id": chat_id, "claimed_at": claimed_at, "source": source}


def legacy_view(todo: Todo) -> dict:
    """Claim view from the latest ``[dev-claim]`` marker. No marker is free."""
    line = get_latest_marker(todo, "[dev-claim]")
    if not line:
        return _view("free", None, None, "none")
    view = _view("free", None, None, "legacy")
    match = _CLAIM_RE.search(line)
    if not match:
        return view
    verb, chat_id = match.group(1), match.group(2)
    if verb == "RELEASE":
        view["state"] = "released"
        return view
    view["state"] = "claimed"
    view["chat_id"] = chat_id
    view["claimed_at"] = line.split(" ", 1)[0]
    return view


def get_view(todo: Todo) -> dict:
    """Column view, or the legacy marker view when the columns were never written."""
    if todo.leader_state == "claimed":
        return _view("claimed", todo.leader_chat, todo.leader_claimed_at, "column")
    if todo.leader_state == "released":
        return _view("released", None, todo.leader_claimed_at, "column")
    return legacy_view(todo)


def _history_todo(row) -> Todo:
    history = []
    for item in row.history or []:
        history.append(item if isinstance(item, TodoHistoryEntry) else TodoHistoryEntry.from_dict(item))
    return Todo(todo_id=row.todo_id, name=getattr(row, "name", "") or "", history=history)


def _validate_chat(session, row, chat_id: str) -> None:
    if not chat_id or not str(chat_id).strip():
        raise LeaderClaimInvalid("chat_id is required")
    from storage.entity.chat import ChatEntity
    chat = (
        session.query(effective_role_expr(COORDINATOR_ROLE).label("is_leader")).select_from(ChatEntity)
        .filter_by(user_id=row.user_id, chat_id=chat_id, trace_id=row.todo_id)
        .first()
    )
    if chat is None:
        raise LeaderClaimInvalid(
            f"chat {chat_id!r} is not a chat of this account in trace {row.todo_id!r}"
        )
    if not chat.is_leader:
        raise LeaderClaimInvalid("only a leader-role chat can hold the leader claim")


def _seed(session, row) -> None:
    """Copy an in-flight legacy CLAIM onto the columns before this transition decides."""
    if row.leader_state is not None:
        return
    seeded = legacy_view(_history_todo(row))
    if seeded["state"] != "claimed" or not seeded["chat_id"]:
        return
    _transition_locked(session, row, {
        "leader_state": "claimed",
        "leader_chat": seeded["chat_id"],
        "leader_claimed_at": seeded["claimed_at"] or get_utc_iso8601_timestamp(),
    }, action="claimed")


def _owner(row) -> Optional[str]:
    return row.leader_chat if row.leader_state == "claimed" else None


def _conflict(owner: Optional[str], reason: str) -> None:
    raise LeaderClaimConflict(reason, owner=owner)


def _holder(row) -> Optional[str]:
    """Current holder from the columns, or from the legacy marker before any seed."""
    if row.leader_state is not None:
        return _owner(row)
    seeded = legacy_view(_history_todo(row))
    return seeded["chat_id"] if seeded["state"] == "claimed" else None


def _claim_locked(session, row, chat_id: str, takeover_from: Optional[str]) -> str:
    _validate_chat(session, row, chat_id)
    # The holder re-claiming (each leader turn) is a no-write resume, legacy rows included.
    if _holder(row) == chat_id and takeover_from in (None, chat_id):
        return "resumed"
    _seed(session, row)
    owner = _owner(row)
    if takeover_from:
        if owner != takeover_from:
            _conflict(owner, f"takeover_from {takeover_from!r} is not the owner ({owner or 'free'})")
        if owner == chat_id:
            return "resumed"
        _transition_locked(session, row, {
            "leader_state": "claimed",
            "leader_chat": chat_id,
            "leader_claimed_at": get_utc_iso8601_timestamp(),
        }, action="taken over")
        return "claimed"
    if owner == chat_id:
        return "resumed"
    if owner:
        _conflict(owner, f"claimed by {owner}")
    _transition_locked(session, row, {
        "leader_state": "claimed",
        "leader_chat": chat_id,
        "leader_claimed_at": get_utc_iso8601_timestamp(),
    }, action="claimed")
    return "claimed"


def _check_handoff(handoff: Optional[str]) -> Optional[str]:
    if handoff is None:
        return None
    if len(handoff) > MAX_HANDOFF:
        raise LeaderClaimInvalid(f"handoff is longer than {MAX_HANDOFF} characters")
    return handoff


def _release_locked(session, row, chat_id: str, handoff: Optional[str]) -> str:
    _validate_chat(session, row, chat_id)
    _seed(session, row)
    if row.leader_state != "claimed":
        return "unchanged"
    if row.leader_chat != chat_id:
        _conflict(row.leader_chat, f"claimed by {row.leader_chat}")
    fields = {"leader_state": "released", "leader_chat": None}
    if handoff is not None:
        fields["progress"] = handoff
    _transition_locked(session, row, fields, action="released")
    return "released"


def _run(user_id: int, todo_id: str, apply) -> Optional[Tuple[dict, str]]:
    outcome = {}

    def mutate(session, row):
        outcome["status"] = apply(session, row)

    todo = mutate_todo(user_id, todo_id, mutate)
    if todo is None:
        return None
    return get_view(todo), outcome["status"]


def claim(user_id: int, todo_id: str, chat_id: str, takeover_from: Optional[str] = None):
    return _run(
        user_id, todo_id,
        lambda session, row: _claim_locked(session, row, chat_id, takeover_from),
    )


def release(user_id: int, todo_id: str, chat_id: str, handoff: Optional[str] = None):
    handoff = _check_handoff(handoff)
    return _run(
        user_id, todo_id,
        lambda session, row: _release_locked(session, row, chat_id, handoff),
    )


def claim_todo(user_id: int, todo_id: str, chat_id: str, takeover_from: Optional[str] = None):
    return claim(user_id, todo_id, chat_id, takeover_from=takeover_from)


def release_todo(user_id: int, todo_id: str, chat_id: str, handoff: Optional[str] = None):
    return release(user_id, todo_id, chat_id, handoff=handoff)
