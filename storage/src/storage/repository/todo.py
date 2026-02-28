"""Function-based todo repository using SQLAlchemy sessions."""

from typing import List, Optional
from sqlalchemy import case
from storage.entity.todo import TodoEntity
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
        status=entity.status,
        progress=entity.progress,
        completed_at=entity.completed_at,
        history=[TodoHistoryEntry.from_dict(h) for h in history],
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_todos(user_id: int, status: Optional[str] = None, priority: Optional[str] = None, limit: int = 50) -> List[Todo]:
    with get_db() as session:
        query = session.query(TodoEntity).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        if priority:
            query = query.filter_by(priority=priority)
        if status == "completed":
            query = query.order_by(TodoEntity.updated_at.desc(), TodoEntity.due_date.asc().nullslast(), _PRIORITY_ORDER.asc())
        else:
            # pending, active, no filter: due_date asc, priority asc, updated_at desc
            query = query.order_by(TodoEntity.due_date.asc().nullslast(), _PRIORITY_ORDER.asc(), TodoEntity.updated_at.desc())
        query = query.limit(limit)
        return [_entity_to_dto(row) for row in query.all()]


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


def delete_todo(user_id: int, todo_id: str) -> bool:
    with get_db() as session:
        count = session.query(TodoEntity).filter_by(user_id=user_id, todo_id=todo_id).delete()
        session.flush()
        return count > 0
