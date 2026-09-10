"""Todo service."""

import ast
from datetime import datetime, timezone
from typing import List, Optional
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.repository import todo as todo_repo
from storage.repository import entity_tag as tag_repo
from storage.repository.entity_tag import normalize_tags
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp

_CHANGED_NOTE_PREFIX = "changed: "


def list_todos(
    user_id: int,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    unread: Optional[bool] = None,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    awaiting: Optional[str] = None,
) -> List[Todo]:
    return todo_repo.list_todos(
        user_id,
        awaiting=awaiting,
        status=status,
        priority=priority,
        query=query,
        unread=unread,
        tag=tag,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=limit,
        offset=offset,
    )


def get_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    return todo_repo.get_todo(user_id, todo_id)


def find_todos_by_ids(user_id: int, todo_ids: List[str]) -> dict:
    """Return {todo_id: Todo} for owner-scoped tag hydration."""
    return todo_repo.find_todos_by_ids(user_id, todo_ids)


def create_todo(
    user_id: int,
    name: str,
    desc: Optional[str] = None,
    tags: Optional[List[str]] = None,
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
) -> Todo:
    # Find smallest available positive integer ID for this user
    existing_ids = todo_repo.get_all_todo_ids(user_id)
    used = set()
    for tid in existing_ids:
        try:
            used.add(int(tid))
        except (ValueError, TypeError):
            pass
    next_id = 1
    while next_id in used:
        next_id += 1

    if tags is not None:
        tags = normalize_tags(tags)

    todo = Todo(
        todo_id=str(next_id),
        name=name,
        desc=desc,
        tags=tags,
        due_date=due_date,
        priority=priority,
        status="pending",
        history=[TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="created")],
    )
    saved = todo_repo.save_todo(user_id, todo)
    tag_repo.sync_tags(user_id, "todo", saved.todo_id, saved.tags or [])
    return saved


def _changed_progress_value(note: str) -> Optional[str]:
    """Extract the new `progress` value from an `update_todo` history note.

    `update_todo` writes notes as `"changed: field1=<repr>, field2=<repr>, ..."`, which is
    valid Python keyword-argument syntax by construction, so it round-trips through ast
    parsing exactly. Returns None if the note isn't in that format, has no `progress` key,
    or fails to parse (e.g. a `created` / `pinned` action note uses a different format).
    """
    if not note.startswith(_CHANGED_NOTE_PREFIX):
        return None
    body = note[len(_CHANGED_NOTE_PREFIX):]
    try:
        call = ast.parse(f"f({body})", mode="eval").body
        changed = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg}
    except (SyntaxError, ValueError, TypeError):
        return None
    value = changed.get("progress")
    return value if isinstance(value, str) else None


def get_latest_marker(todo: Todo, marker: str) -> Optional[str]:
    """Return the most recent history entry whose new progress value starts with `marker`,
    formatted as "<timestamp> <note>", or None. Used to surface a single compact status
    line (e.g. the dev coordinator's `[dev-claim]` lock marker) without exposing full
    history via the CLI.

    Matches only entries where `marker` is the actual prefix of the progress text that was
    written, not an incidental mention elsewhere in a note's prose (e.g. a progress update
    that happens to reference "[dev-claim]" mid-sentence must not be mistaken for a real
    marker entry).
    """
    for entry in reversed(todo.history or []):
        if not entry.note:
            continue
        progress_value = _changed_progress_value(entry.note)
        if progress_value is not None and progress_value.startswith(marker):
            return f"{entry.timestamp} {entry.note}"
    return None


STATUS_ACTION = {
    "pending": "deactivated", "active": "activated",
    "completed": "completed", "deleted": "deleted",
}


def _apply_fields(session, row, fields, *, action="updated", internal=False):
    fields = dict(fields)
    if "status" in fields and fields["status"] not in STATUS_ACTION:
        raise ValueError("Invalid todo status")
    if "awaiting" in fields:
        if fields["awaiting"] == "none":
            fields["awaiting"] = None
        allowed = {None, "question", "review", "external"}
        if internal:
            allowed.add("stalled")
        if fields["awaiting"] not in allowed:
            raise ValueError("Invalid awaiting reason")
    reason = fields.get("awaiting", row.awaiting)
    status = fields.get("status", row.status)
    if status in {"completed", "deleted"}:
        if fields.get("awaiting") is not None:
            raise ValueError("Closed todos cannot await")
        reason = None
        fields["awaiting"] = None
    if reason != "question":
        if fields.get("awaiting_chat") is not None:
            raise ValueError("awaiting_chat is only valid for question")
        fields["awaiting_chat"] = None
    elif any(k in fields for k in ("awaiting", "awaiting_chat")):
        from storage.entity.chat import ChatEntity
        pointer = fields.get("awaiting_chat", row.awaiting_chat)
        if not pointer or not session.query(ChatEntity.id).filter_by(
            user_id=row.user_id, chat_id=pointer, trace_id=row.todo_id,
        ).first():
            raise ValueError("Question requires a same-owner, same-trace awaiting_chat")
    if reason != "external":
        if fields.get("awaiting_until") is not None:
            raise ValueError("awaiting_until is only valid for external")
        fields["awaiting_until"] = None
    elif fields.get("awaiting_until") is not None:
        try:
            dt = datetime.fromisoformat(fields["awaiting_until"])
            if dt.utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("awaiting_until must be a timezone-aware ISO timestamp")
        fields["awaiting_until"] = dt.astimezone(timezone.utc).isoformat()
    if "status" in fields and fields["status"] != row.status:
        fields["completed_at"] = get_utc_iso8601_timestamp() if status == "completed" else None
        if row.pinned and "pinned" not in fields:
            fields["pinned"] = False
    if "tags" in fields and fields["tags"] is not None:
        fields["tags"] = normalize_tags(fields["tags"])
    changed = {k: v for k, v in fields.items() if getattr(row, k) != v}
    if not changed:
        return False
    for key, value in changed.items():
        setattr(row, key, value)
    row.history = [*(row.history or []), TodoHistoryEntry(
        timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
        action=action, note=f"changed: {', '.join(f'{k}={v!r}' for k, v in changed.items())}",
    ).to_dict()]
    return True


def update_todo(user_id: int, todo_id: str, **fields) -> Optional[Todo]:
    allowed = {"name", "desc", "tags", "due_date", "priority", "progress", "status",
               "awaiting", "awaiting_chat", "awaiting_until", "pinned"}
    if fields.keys() - allowed:
        raise ValueError("Unknown todo fields")
    todo = todo_repo.mutate_todo(user_id, todo_id, lambda session, row: _apply_fields(session, row, fields))
    if todo and "tags" in fields:
        tag_repo.sync_tags(user_id, "todo", todo.todo_id, todo.tags or [])
    return todo


def pin_todo(user_id: int, todo_id: str, pinned: bool) -> Optional[Todo]:
    return todo_repo.mutate_todo(user_id, todo_id, lambda session, row: _apply_fields(
        session, row, {"pinned": pinned}, action="pinned" if pinned else "unpinned"))


def update_status(user_id: int, todo_id: str, status: str) -> Optional[Todo]:
    return todo_repo.mutate_todo(user_id, todo_id, lambda session, row: _apply_fields(
        session, row, {"status": status}, action=STATUS_ACTION.get(status, status)))


def clear_awaiting_locked(session, row, reasons):
    """Caller holds the todo lock, optionally alongside an accepted chat write."""
    if row is not None and row.awaiting in reasons:
        return _apply_fields(session, row, {"awaiting": None}, internal=True)
    return False


def claim_stalled(user_id: int, todo_id: str, *, expected_updated_at_unix: int,
                  expected_awaiting: Optional[str] = None, recheck=None) -> bool:
    """Claim an observed fault once. Evidence recheck runs under the todo lock.

    The runtime/watchdog caller must recheck its process snapshot and activity
    deadline here; SQL running chats are always checked by this primitive.
    """
    from storage.entity.chat import ChatEntity
    won = False

    def claim(session, row):
        nonlocal won
        if (row.status != "active" or row.awaiting not in {None, "external"}
                or row.awaiting != expected_awaiting
                or row.updated_at_unix != expected_updated_at_unix):
            return
        if session.query(ChatEntity.id).filter_by(
            user_id=user_id, trace_id=todo_id, status="running",
        ).first():
            return
        if recheck is None or not recheck(session, row):
            return
        won = _apply_fields(session, row, {"awaiting": "stalled"}, internal=True)

    todo_repo.mutate_todo(user_id, todo_id, claim)
    return won


def bulk_update_todos(
    user_id: int,
    todo_ids: List[str],
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    pinned: Optional[bool] = None,
) -> int:
    """Apply one or more updates to a batch of todos, reusing the single-todo
    service functions so each keeps its own history semantics. Missing todo_ids
    are silently skipped. Returns the count of todos that were updated."""
    count = 0
    for todo_id in todo_ids:
        updated = False
        if status is not None:
            if update_status(user_id, todo_id, status) is not None:
                updated = True
        if priority is not None:
            if update_todo(user_id, todo_id, priority=priority) is not None:
                updated = True
        if pinned is not None:
            if pin_todo(user_id, todo_id, pinned) is not None:
                updated = True
        if updated:
            count += 1
    return count
