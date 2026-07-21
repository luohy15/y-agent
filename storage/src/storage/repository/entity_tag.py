"""Function-based entity_tag repository.

entity_tag is the single cross-entity queryable tag projection: rows are
(user_id, entity_type, entity_id, tag). Each carrier entity keeps its own
authoring surface (e.g. note.front_matter.tags, todo.tags) and calls
sync_tags() to reconcile the projection; the 7 direct carriers (chat,
calendar_event, reminder, routine, link, email, rss_feed) write here directly
via add_tag/remove_tag.
"""

from typing import List, Tuple

from sqlalchemy import func
from storage.entity.entity_tag import EntityTagEntity
from storage.database.base import get_db


def sync_tags(user_id: int, entity_type: str, entity_id: str, tags: List[str]) -> None:
    """Reconcile entity_tag rows for (entity_type, entity_id) to exactly `tags`."""
    wanted = set(tags)
    with get_db() as session:
        existing = session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id
        ).all()
        existing_tags = {row.tag for row in existing}
        for row in existing:
            if row.tag not in wanted:
                session.delete(row)
        for tag in wanted - existing_tags:
            session.add(EntityTagEntity(user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag))


def add_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    """Add a single tag. Returns True if created, False if already present."""
    with get_db() as session:
        exists = session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag
        ).first()
        if exists:
            return False
        session.add(EntityTagEntity(user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag))
        return True


def remove_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    """Remove a single tag. Returns True if deleted, False if not found."""
    with get_db() as session:
        row = session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag
        ).first()
        if not row:
            return False
        session.delete(row)
        return True


def list_tags(user_id: int, entity_type: str, entity_id: str) -> List[str]:
    """Return tags currently projected for one entity."""
    with get_db() as session:
        rows = session.query(EntityTagEntity.tag).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id
        ).all()
        return [r.tag for r in rows]


def find_by_tag(user_id: int, tag: str, prefix: bool = False) -> List[Tuple[str, str]]:
    """Return (entity_type, entity_id) pairs matching `tag` (exact, or prefix e.g. 'work/')."""
    with get_db() as session:
        query = session.query(EntityTagEntity.entity_type, EntityTagEntity.entity_id)
        if prefix:
            # An entity can match a prefix through more than one tag (e.g. both
            # "work/y-agent" and "work/finance"), so de-dupe (entity_type, entity_id).
            query = query.filter(EntityTagEntity.user_id == user_id, EntityTagEntity.tag.like(f"{tag}%")).distinct()
        else:
            # The (user_id, entity_type, entity_id, tag) unique constraint already
            # guarantees at most one row per entity for an exact tag match.
            query = query.filter_by(user_id=user_id, tag=tag)
        return [(r.entity_type, r.entity_id) for r in query.all()]


def distinct_tags(user_id: int) -> List[Tuple[str, int]]:
    """Return (tag, count) pairs for every distinct tag the user has used, sorted by tag."""
    with get_db() as session:
        rows = session.query(EntityTagEntity.tag, func.count(EntityTagEntity.id)).filter_by(
            user_id=user_id
        ).group_by(EntityTagEntity.tag).order_by(EntityTagEntity.tag).all()
        return [(row[0], row[1]) for row in rows]


def delete_for_entity(user_id: int, entity_type: str, entity_id: str) -> int:
    """Delete all tags for one entity (call from that entity's delete path). Returns rows deleted."""
    with get_db() as session:
        return session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id
        ).delete()
