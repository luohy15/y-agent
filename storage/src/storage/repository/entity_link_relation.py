"""Function-based entity-link relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.entity_link_relation import EntityLinkRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, entity_id: str, activity_id: str) -> bool:
    """Insert an entity-link relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        row = EntityLinkRelationEntity(user_id=user_id, entity_id=entity_id, activity_id=activity_id)
        session.add(row)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, entity_id: str, activity_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        row = session.query(EntityLinkRelationEntity).filter_by(
            user_id=user_id, entity_id=entity_id, activity_id=activity_id
        ).first()
        if not row:
            return False
        session.delete(row)
        return True


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    """Return list of activity_ids associated with an entity."""
    with get_db() as session:
        rows = session.query(EntityLinkRelationEntity.activity_id).filter_by(
            user_id=user_id, entity_id=entity_id
        ).all()
        return [r.activity_id for r in rows]


def list_by_activity(user_id: int, activity_id: str) -> List[str]:
    """Return list of entity_ids associated with an activity."""
    with get_db() as session:
        rows = session.query(EntityLinkRelationEntity.entity_id).filter_by(
            user_id=user_id, activity_id=activity_id
        ).all()
        return [r.entity_id for r in rows]
