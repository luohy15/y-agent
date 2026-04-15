"""Function-based note-todo relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.note_todo_relation import NoteTodoRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, note_id: str, todo_id: str) -> bool:
    """Insert a note-todo relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        entity = NoteTodoRelationEntity(user_id=user_id, note_id=note_id, todo_id=todo_id)
        session.add(entity)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, note_id: str, todo_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        entity = session.query(NoteTodoRelationEntity).filter_by(
            user_id=user_id, note_id=note_id, todo_id=todo_id
        ).first()
        if not entity:
            return False
        session.delete(entity)
        return True


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    """Return list of note_ids associated with a todo."""
    with get_db() as session:
        rows = session.query(NoteTodoRelationEntity.note_id).filter_by(
            user_id=user_id, todo_id=todo_id
        ).all()
        return [r.note_id for r in rows]


def list_by_note(user_id: int, note_id: str) -> List[str]:
    """Return list of todo_ids associated with a note."""
    with get_db() as session:
        rows = session.query(NoteTodoRelationEntity.todo_id).filter_by(
            user_id=user_id, note_id=note_id
        ).all()
        return [r.todo_id for r in rows]
