"""Function-based link-todo relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.link_todo_relation import LinkTodoRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, activity_id: str, todo_id: str) -> bool:
    """Insert a link-todo relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        entity = LinkTodoRelationEntity(user_id=user_id, activity_id=activity_id, todo_id=todo_id)
        session.add(entity)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, activity_id: str, todo_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        entity = session.query(LinkTodoRelationEntity).filter_by(
            user_id=user_id, activity_id=activity_id, todo_id=todo_id
        ).first()
        if not entity:
            return False
        session.delete(entity)
        return True


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    """Return list of activity_ids associated with a todo."""
    with get_db() as session:
        rows = session.query(LinkTodoRelationEntity.activity_id).filter_by(
            user_id=user_id, todo_id=todo_id
        ).all()
        return [r.activity_id for r in rows]


def list_by_activity(user_id: int, activity_id: str) -> List[str]:
    """Return list of todo_ids associated with an activity."""
    with get_db() as session:
        rows = session.query(LinkTodoRelationEntity.todo_id).filter_by(
            user_id=user_id, activity_id=activity_id
        ).all()
        return [r.todo_id for r in rows]
