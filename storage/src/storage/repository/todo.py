"""Function-based todo repository using SQLAlchemy sessions."""

from datetime import date, timedelta
from typing import List, Optional
from sqlalchemy import case, func
from storage.entity.todo import TodoEntity
from storage.entity.chat import ChatEntity
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.database.base import get_db

# Match web UI sort: high=0, medium=1, low=2, other=3
_PRIORITY_ORDER = case(
    (TodoEntity.priority == "high", 0),
    (TodoEntity.priority == "medium", 1),
    (TodoEntity.priority == "low", 2),
    else_=3,
)


def _entity_to_dto(entity: TodoEntity) -> Todo:
    history = entity.history or []
    return Todo(
        todo_id=entity.todo_id,
        name=entity.name,
        desc=entity.desc,
        tags=entity.tags,
        due_date=entity.due_date,
        priority=entity.priority,
        pinned=bool(entity.pinned) if entity.pinned is not None else False,
        status=entity.status,
        progress=entity.progress,
        completed_at=entity.completed_at,
        history=[TodoHistoryEntry.from_dict(h) for h in history],
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_todos(user_id: int, status: Optional[str] = None, priority: Optional[str] = None, query: Optional[str] = None, unread: Optional[bool] = None, limit: int = 50, offset: int = 0) -> List[Todo]:
    with get_db() as session:
        # Per-trace max chat activity: chat.trace_id == todo.todo_id by convention.
        # Falls back to todo.updated_at_unix when a todo has no associated chat.
        chat_max = (
            session.query(
                ChatEntity.trace_id.label("tid"),
                func.max(ChatEntity.updated_at_unix).label("max_updated"),
            )
            .filter(ChatEntity.user_id == user_id)
            .filter(ChatEntity.trace_id.isnot(None))
            .group_by(ChatEntity.trace_id)
            .subquery()
        )
        effective_updated = func.coalesce(chat_max.c.max_updated, TodoEntity.updated_at_unix)

        q = (session.query(TodoEntity)
             .outerjoin(chat_max, chat_max.c.tid == TodoEntity.todo_id)
             .filter(TodoEntity.user_id == user_id))
        if status:
            q = q.filter(TodoEntity.status == status)
        if priority:
            q = q.filter(TodoEntity.priority == priority)
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                TodoEntity.name.ilike(pattern) | TodoEntity.todo_id.ilike(pattern) | TodoEntity.desc.ilike(pattern)
            )
        if unread:
            unread_exists = (
                session.query(ChatEntity.trace_id)
                .filter(ChatEntity.user_id == user_id)
                .filter(ChatEntity.unread.is_(True))
                .filter(ChatEntity.trace_id == TodoEntity.todo_id)
                .exists()
            )
            q = q.filter(unread_exists)
        if status == "pending":
            # pending: two-group sorting
            # Group 0: has due_date within today + 14 days → sort by due_date ASC
            # Group 1: everything else → sort by priority ASC, effective_updated DESC
            cutoff = (date.today() + timedelta(days=14)).isoformat()
            is_soon = case(
                (TodoEntity.due_date.isnot(None) & (TodoEntity.due_date != "") & (TodoEntity.due_date <= cutoff), 0),
                else_=1,
            )
            q = q.order_by(
                TodoEntity.pinned.desc(),
                is_soon.asc(),
                case((is_soon == 0, TodoEntity.due_date), else_=None).asc(),
                case((is_soon == 1, _PRIORITY_ORDER), else_=None).asc(),
                case((is_soon == 1, effective_updated), else_=None).desc(),
            )
        elif status == "active":
            # active: due_date asc (nulls last), priority asc, effective_updated desc
            due_date_sort = func.nullif(TodoEntity.due_date, "")
            q = q.order_by(TodoEntity.pinned.desc(), due_date_sort.asc().nullslast(), _PRIORITY_ORDER.asc(), effective_updated.desc())
        else:
            # completed or no filter: effective_updated desc
            q = q.order_by(TodoEntity.pinned.desc(), effective_updated.desc())
        q = q.offset(offset).limit(limit)
        return [_entity_to_dto(row) for row in q.all()]


def get_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    with get_db() as session:
        row = session.query(TodoEntity).filter_by(user_id=user_id, todo_id=todo_id).first()
        if row:
            return _entity_to_dto(row)
        return None


def save_todo(user_id: int, todo: Todo) -> Todo:
    with get_db() as session:
        entity = session.query(TodoEntity).filter_by(user_id=user_id, todo_id=todo.todo_id).first()
        fields = dict(
            name=todo.name,
            desc=todo.desc,
            tags=todo.tags,
            due_date=todo.due_date,
            priority=todo.priority,
            pinned=todo.pinned,
            status=todo.status,
            progress=todo.progress,
            completed_at=todo.completed_at,
            history=[h.to_dict() for h in (todo.history or [])],
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = TodoEntity(user_id=user_id, todo_id=todo.todo_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def find_todos_by_ids(user_id: int, todo_ids: List[str]) -> dict:
    """Return {todo_id: Todo} for the given IDs."""
    with get_db() as session:
        rows = (session.query(TodoEntity)
                .filter_by(user_id=user_id)
                .filter(TodoEntity.todo_id.in_(todo_ids))
                .all())
        return {row.todo_id: _entity_to_dto(row) for row in rows}


def get_all_todo_ids(user_id: int) -> List[str]:
    """Return all todo_ids for a user."""
    with get_db() as session:
        rows = session.query(TodoEntity.todo_id).filter_by(user_id=user_id).all()
        return [row[0] for row in rows]


def delete_todo(user_id: int, todo_id: str) -> bool:
    with get_db() as session:
        count = session.query(TodoEntity).filter_by(user_id=user_id, todo_id=todo_id).delete()
        session.flush()
        return count > 0
