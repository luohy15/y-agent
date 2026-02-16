"""Todo service."""

from typing import List, Optional
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.repository import todo as todo_repo
from storage.util import generate_id, get_utc_iso8601_timestamp, get_unix_timestamp


def list_todos(user_id: int, status: Optional[str] = None, priority: Optional[str] = None, limit: int = 50) -> List[Todo]:
    return todo_repo.list_todos(user_id, status=status, priority=priority, limit=limit)


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
    todo = Todo(
        todo_id=generate_id(),
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
            note=f"changed: {', '.join(changed)}",
        ))
        todo.history = history
        return todo_repo.save_todo(user_id, todo)
    return todo


def finish_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    todo.status = "completed"
    todo.completed_at = get_utc_iso8601_timestamp()
    history = todo.history or []
    history.append(TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="completed"))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)


def delete_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    todo.status = "deleted"
    history = todo.history or []
    history.append(TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="deleted"))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)


def activate_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    todo.status = "active"
    history = todo.history or []
    history.append(TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="activated"))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)


def deactivate_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        return None
    todo.status = "pending"
    history = todo.history or []
    history.append(TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="deactivated"))
    todo.history = history
    return todo_repo.save_todo(user_id, todo)
