"""Function-based entity-note relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.entity_note_relation import EntityNoteRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, entity_id: str, note_id: str) -> bool:
    """Insert an entity-note relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        row = EntityNoteRelationEntity(user_id=user_id, entity_id=entity_id, note_id=note_id)
        session.add(row)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, entity_id: str, note_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        row = session.query(EntityNoteRelationEntity).filter_by(
            user_id=user_id, entity_id=entity_id, note_id=note_id
        ).first()
        if not row:
            return False
        session.delete(row)
        return True


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    """Return list of note_ids associated with an entity."""
    with get_db() as session:
        rows = session.query(EntityNoteRelationEntity.note_id).filter_by(
            user_id=user_id, entity_id=entity_id
        ).all()
        return [r.note_id for r in rows]


def list_by_note(user_id: int, note_id: str) -> List[str]:
    """Return list of entity_ids associated with a note."""
    with get_db() as session:
        rows = session.query(EntityNoteRelationEntity.entity_id).filter_by(
            user_id=user_id, note_id=note_id
        ).all()
        return [r.entity_id for r in rows]
