"""Function-based entity-rss relation repository."""

from typing import List
from sqlalchemy.exc import IntegrityError
from storage.entity.entity_rss_relation import EntityRssRelationEntity
from storage.database.base import get_db


def create_relation(user_id: int, entity_id: str, rss_feed_id: str) -> bool:
    """Insert an entity-rss relation. Returns True if created, False if duplicate."""
    with get_db() as session:
        row = EntityRssRelationEntity(user_id=user_id, entity_id=entity_id, rss_feed_id=rss_feed_id)
        session.add(row)
        try:
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def delete_relation(user_id: int, entity_id: str, rss_feed_id: str) -> bool:
    """Delete a relation. Returns True if deleted, False if not found."""
    with get_db() as session:
        row = session.query(EntityRssRelationEntity).filter_by(
            user_id=user_id, entity_id=entity_id, rss_feed_id=rss_feed_id
        ).first()
        if not row:
            return False
        session.delete(row)
        return True


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    """Return list of rss_feed_ids associated with an entity."""
    with get_db() as session:
        rows = session.query(EntityRssRelationEntity.rss_feed_id).filter_by(
            user_id=user_id, entity_id=entity_id
        ).all()
        return [r.rss_feed_id for r in rows]


def list_by_feed(user_id: int, rss_feed_id: str) -> List[str]:
    """Return list of entity_ids associated with an rss feed."""
    with get_db() as session:
        rows = session.query(EntityRssRelationEntity.entity_id).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id
        ).all()
        return [r.entity_id for r in rows]
