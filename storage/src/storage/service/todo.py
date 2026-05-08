"""Todo service."""

import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.repository import todo as todo_repo
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


def _get_configured_tz():
    """Return the configured timezone, falling back to system local."""
    from dateutil import tz as dateutil_tz
    tz_name = os.getenv("Y_AGENT_TIMEZONE")
    if tz_name:
        tz = dateutil_tz.gettz(tz_name)
        if tz:
            return tz
    return dateutil_tz.tzlocal()


def _local_date_to_utc_iso(date_str: str) -> str:
    """Convert YYYY-MM-DD (in configured local tz) to UTC ISO 8601 'start of day'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_get_configured_tz())
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_dt.microsecond // 1000:03d}Z"


def _local_date_end_to_utc_iso(date_str: str) -> str:
    """Convert YYYY-MM-DD to UTC ISO 8601 'start of next day' (exclusive upper bound)."""
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return _local_date_to_utc_iso(next_day)


def list_todos(user_id: int, status: Optional[str] = None, priority: Optional[str] = None, query: Optional[str] = None, unread: Optional[bool] = None, completed_on: Optional[str] = None, completed_since: Optional[str] = None, completed_until: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Todo]:
    since_iso: Optional[str] = None
    until_iso: Optional[str] = None
    if completed_on:
        since_iso = _local_date_to_utc_iso(completed_on)
        until_iso = _local_date_end_to_utc_iso(completed_on)
    else:
        if completed_since:
            since_iso = _local_date_to_utc_iso(completed_since)
        if completed_until:
            until_iso = _local_date_end_to_utc_iso(completed_until)
    return todo_repo.list_todos(user_id, status=status, priority=priority, query=query, unread=unread, completed_since=since_iso, completed_until=until_iso, limit=limit, offset=offset)


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
    return todo_repo.save_todo(user_id, todo)


def update_todo(user_id: int, todo_id: str, **fields) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
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
        return todo_repo.save_todo(user_id, todo)
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
