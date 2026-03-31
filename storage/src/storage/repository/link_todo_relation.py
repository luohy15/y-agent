"""Function-based link-todo relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.link_todo_relation import LinkTodoRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, link_id: str, todo_id: str) -> bool:
    """Insert a link-todo relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        entity = LinkTodoRelationEntity(user_id=user_id, link_id=link_id, todo_id=todo_id)
        session.add(entity)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, link_id: str, todo_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        entity = session.query(LinkTodoRelationEntity).filter_by(
            user_id=user_id, link_id=link_id, todo_id=todo_id
        ).first()
        if not entity:
            return False
        session.delete(entity)
        return True


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    """Return list of link_ids associated with a todo."""
    with get_db() as session:
        rows = session.query(LinkTodoRelationEntity.link_id).filter_by(
            user_id=user_id, todo_id=todo_id
        ).all()
        return [r.link_id for r in rows]


def list_by_link(user_id: int, link_id: str) -> List[str]:
    """Return list of todo_ids associated with a link."""
    with get_db() as session:
        rows = session.query(LinkTodoRelationEntity.todo_id).filter_by(
            user_id=user_id, link_id=link_id
        ).all()
        return [r.todo_id for r in rows]
