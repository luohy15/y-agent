"""Function-based entity_tag repository.

entity_tag is the single cross-entity queryable tag projection: rows are
(user_id, entity_type, entity_id, tag). Each carrier entity keeps its own
authoring surface (e.g. note.front_matter.tags, todo.tags) and calls
sync_tags() to reconcile the projection; direct carriers write here with
add_tag/remove_tag. Email is the exception: its service validates canonical
thread keys and, for additions, existing vocabulary before writing through its
dedicated repository helpers.

Write-time normalization (todo 3159 P1): every tag write path lowercases,
trims, and maps underscore to hyphen. Project tags always use the hyphen form
even when the repo directory under code/ uses underscores (e.g.
code/alpha_vantage_mcp → alpha-vantage-mcp). No auto-singularize.

Compatibility registration (todo 3290): add_tag() and sync_tags() also
register each normalized tag in tag_vocabulary, in the same transaction as
the entity_tag write, so any caller (including callers that predate the
create-vocabulary route) keeps the vocabulary durable and the entity_tag
projection a subset of it.
"""

from typing import Iterable, List, Optional, Tuple, Union

from sqlalchemy import func
from storage.entity.entity_tag import EntityTagEntity
from storage.database.base import get_db
from storage.repository import tag_vocabulary as vocabulary_repo


def normalize_tag(tag: str) -> Optional[str]:
    """Lowercase + trim + map `_`→`-`. Empty after trim becomes None."""
    if not isinstance(tag, str):
        return None
    t = tag.strip().lower().replace("_", "-")
    return t if t else None


def normalize_tags(tags: Optional[Union[str, Iterable]]) -> List[str]:
    """Normalize a tags payload to a deduped lowercase/hyphen list (order-preserving)."""
    if not tags:
        return []
    if isinstance(tags, str):
        t = normalize_tag(tags)
        return [t] if t else []
    out: List[str] = []
    seen = set()
    for item in tags:
        t = normalize_tag(item) if isinstance(item, str) else None
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def sync_tags(user_id: int, entity_type: str, entity_id: str, tags: List[str]) -> None:
    """Reconcile entity_tag rows for (entity_type, entity_id) to exactly `tags`."""
    wanted = set(normalize_tags(tags))
    with get_db() as session:
        # Register vocabulary before touching entity_tag: ensure() may run a
        # nested SAVEPOINT on SQLite whose flush would otherwise sweep up any
        # already-pending entity_tag delete/add and roll it back together with
        # a spurious vocabulary race.
        for tag in wanted:
            vocabulary_repo.ensure(session, user_id, tag)
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
    tag = normalize_tag(tag)
    if not tag:
        return False
    with get_db() as session:
        exists = session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag
        ).first()
        vocabulary_repo.ensure(session, user_id, tag)
        if exists:
            return False
        session.add(EntityTagEntity(user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag))
        return True


def remove_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    """Remove a single tag. Returns True if deleted, False if not found."""
    tag = normalize_tag(tag)
    if not tag:
        return False
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
