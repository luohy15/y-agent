"""Todo service."""

import ast
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
) -> List[Todo]:
    return todo_repo.list_todos(
        user_id,
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


def update_todo(user_id: int, todo_id: str, **fields) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    if "tags" in fields and fields["tags"] is not None:
        fields["tags"] = normalize_tags(fields["tags"])
    changed = []
    for key, value in fields.items():
        if hasattr(todo, key) and getattr(todo, key) != value:
            setattr(todo, key, value)
            changed.append(key)
    if changed:
        history = todo.history or []
        history.append(TodoHistoryEntry(
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
            action="updated",
            note=f"changed: {', '.join(f'{k}={getattr(todo, k)!r}' for k in changed)}",
        ))
        todo.history = history
        todo = todo_repo.save_todo(user_id, todo)
    if "tags" in fields:
        tag_repo.sync_tags(user_id, "todo", todo.todo_id, todo.tags or [])
    return todo


def pin_todo(user_id: int, todo_id: str, pinned: bool) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    todo.pinned = pinned
    history = todo.history or []
    action = "pinned" if pinned else "unpinned"
    history.append(TodoHistoryEntry(
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        action=action,
    ))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)


STATUS_ACTION = {
    "pending": "deactivated",
    "active": "activated",
    "completed": "completed",
    "deleted": "deleted",
}


def update_status(user_id: int, todo_id: str, status: str) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    old_status = todo.status
    todo.status = status
    if status == "completed":
        todo.completed_at = get_utc_iso8601_timestamp()
    elif old_status == "completed":
        todo.completed_at = None
    action = STATUS_ACTION.get(status, status)
    history = todo.history or []
    history.append(TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action=action))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)


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
