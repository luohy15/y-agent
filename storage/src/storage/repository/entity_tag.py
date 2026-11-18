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

Membership writes require existing owner vocabulary (todo 4277). Validation
and projection changes share the owner lock and transaction with carrier saves;
only explicit vocabulary creation and coordinated rename register new names.
"""

from typing import Iterable, List, Optional, Tuple, Union

from sqlalchemy import String, func, literal_column, select, union_all
from storage.entity.entity_tag import EntityTagEntity
from storage.entity.module import ModuleEntity
from storage.entity.module_version import ModuleVersionEntity
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


class UnknownTagError(ValueError):
    """A membership write referenced an unregistered vocabulary spelling."""


def require_known_tags(session, user_id: int, tags) -> List[str]:
    """Normalize and validate the complete set while holding the owner lock."""
    from storage.entity.tag_vocabulary import TagVocabularyEntity

    vocabulary_repo.lock_owner(session, user_id)
    normalized = normalize_tags(tags)
    if normalized:
        from storage.crypto.query import active
        from storage.crypto.tenant import blind_for_user
        if active(session, user_id):
            tokens = {tag: blind_for_user(session, user_id, "tag", tag) for tag in normalized}
            rows = session.query(TagVocabularyEntity).filter(
                TagVocabularyEntity.user_id == user_id,
                TagVocabularyEntity.tag_bidx.in_(list(tokens.values())),
            ).all()
            known = {row.tag for row in rows}
        else:
            known = {row[0] for row in session.query(TagVocabularyEntity.tag).filter(
                TagVocabularyEntity.user_id == user_id,
                TagVocabularyEntity.tag.in_(normalized),
            ).all()}
        unknown = [tag for tag in normalized if tag not in known]
        if unknown:
            raise UnknownTagError(f"unknown tag(s): {', '.join(unknown)}; see y tag list")
    return normalized


def sync_tags_locked(session, user_id: int, entity_type: str, entity_id: str, tags) -> None:
    """Validate and reconcile in the carrier's transaction, before saving it."""
    wanted = set(require_known_tags(session, user_id, tags))
    existing = session.query(EntityTagEntity).filter_by(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id
    ).all()
    existing_tags = {row.tag for row in existing}
    for row in existing:
        if row.tag not in wanted:
            session.delete(row)
    for tag in wanted - existing_tags:
        session.add(EntityTagEntity(user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag))


def sync_tags(user_id: int, entity_type: str, entity_id: str, tags: List[str]) -> None:
    """Reconcile entity_tag rows for (entity_type, entity_id) to exactly `tags`."""
    with get_db() as session:
        sync_tags_locked(session, user_id, entity_type, entity_id, tags)


def add_tag_locked(
    session,
    user_id: int,
    entity_type: str,
    entity_id: str,
    tag: str,
    *,
    require_existing: bool = True,
) -> bool:
    """Add one tag inside a caller transaction that already holds the owner lock.

    `require_existing` is retained for callers; False no longer permits creation.
    """
    tag = normalize_tag(tag)
    if not tag:
        return False
    require_known_tags(session, user_id, [tag])
    from storage.crypto.query import match_bidx
    exists = session.query(EntityTagEntity).filter(
        EntityTagEntity.user_id == user_id,
        EntityTagEntity.entity_type == entity_type,
        EntityTagEntity.entity_id == entity_id,
        match_bidx(session, user_id, EntityTagEntity.tag, EntityTagEntity.tag_bidx, "tag", tag),
    ).first()
    if exists:
        return False
    session.add(EntityTagEntity(user_id=user_id, entity_type=entity_type, entity_id=entity_id, tag=tag))
    return True


def add_tag(
    user_id: int,
    entity_type: str,
    entity_id: str,
    tag: str,
    *,
    require_existing: bool = True,
) -> bool:
    """Add a single tag. Returns True if created, False if already present."""
    if not normalize_tag(tag):
        return False
    with get_db() as session:
        vocabulary_repo.lock_owner(session, user_id)
        return add_tag_locked(
            session, user_id, entity_type, entity_id, tag, require_existing=require_existing
        )


def remove_tag_locked(session, user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    """Remove one tag inside a caller transaction that already holds the owner lock."""
    tag = normalize_tag(tag)
    if not tag:
        return False
    from storage.crypto.query import match_bidx
    row = session.query(EntityTagEntity).filter(
        EntityTagEntity.user_id == user_id,
        EntityTagEntity.entity_type == entity_type,
        EntityTagEntity.entity_id == entity_id,
        match_bidx(session, user_id, EntityTagEntity.tag, EntityTagEntity.tag_bidx, "tag", tag),
    ).first()
    if not row:
        return False
    session.delete(row)
    return True


def remove_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    """Remove a single tag. Returns True if deleted, False if not found."""
    if not normalize_tag(tag):
        return False
    with get_db() as session:
        vocabulary_repo.lock_owner(session, user_id)
        return remove_tag_locked(session, user_id, entity_type, entity_id, tag)


def list_tags(user_id: int, entity_type: str, entity_id: str) -> List[str]:
    """Return tags currently projected for one entity."""
    with get_db() as session:
        from storage.crypto.query import active
        if active(session, user_id):
            rows = session.query(EntityTagEntity).filter_by(
                user_id=user_id, entity_type=entity_type, entity_id=entity_id
            ).all()
            return [r.tag for r in rows]
        rows = session.query(EntityTagEntity.tag).filter_by(
            user_id=user_id, entity_type=entity_type, entity_id=entity_id
        ).all()
        return [r.tag for r in rows]


def find_by_tag(user_id: int, tag: str, prefix: bool = False) -> List[Tuple[str, str]]:
    """Return (entity_type, entity_id) pairs matching `tag` (exact, or prefix e.g. 'work/')."""
    with get_db() as session:
        from storage.crypto.query import prefix_or_exact
        query = session.query(EntityTagEntity.entity_type, EntityTagEntity.entity_id)
        # Prefix matches de-dupe because one entity can carry more than one tag.
        # Encrypted tenants have no server-side prefix index, so prefix is exact-only.
        query = query.filter(
            EntityTagEntity.user_id == user_id,
            prefix_or_exact(
                session, user_id, EntityTagEntity.tag, EntityTagEntity.tag_bidx, "tag", tag, prefix,
            ),
        )
        if prefix:
            query = query.distinct()
        return [(r.entity_type, r.entity_id) for r in query.all()]


def find_by_tag_with_carriers(
    user_id: int, tag: str, prefix: bool = False
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """`find_by_tag` pairs plus the owner's enabled active-version carrier
    claims as raw (slug, tag_carriers) rows, in one statement (todo 3838).

    The claim rows ride a tagged UNION ALL so tag lookup costs one round trip
    no matter how many resolver-less types it returns.
    """
    kind = literal_column("'pair'", String).label("kind")
    claims = select(
        literal_column("'claim'", String), ModuleEntity.slug, ModuleVersionEntity.tag_carriers
    ).join_from(
        ModuleEntity,
        ModuleVersionEntity,
        (ModuleVersionEntity.user_id == ModuleEntity.user_id)
        & (ModuleVersionEntity.version_id == ModuleEntity.active_version_id),
    ).where(ModuleEntity.user_id == user_id, ModuleEntity.enabled.is_(True))
    with get_db() as session:
        from storage.crypto.query import prefix_or_exact
        pairs = select(
            kind, EntityTagEntity.entity_type.label("a"), EntityTagEntity.entity_id.label("b")
        ).where(
            EntityTagEntity.user_id == user_id,
            prefix_or_exact(
                session, user_id, EntityTagEntity.tag, EntityTagEntity.tag_bidx, "tag", tag, prefix,
            ),
        )
        if prefix:
            pairs = pairs.distinct()
        rows = session.execute(union_all(pairs, claims)).all()
    found: List[Tuple[str, str]] = []
    claimed: List[Tuple[str, str]] = []
    for row_kind, a, b in rows:
        (found if row_kind == "pair" else claimed).append((a, b))
    return found, claimed


def distinct_tags(user_id: int) -> List[Tuple[str, int]]:
    """Return (tag, count) pairs for every distinct tag the user has used, sorted by tag."""
    with get_db() as session:
        from storage.crypto.query import active
        if active(session, user_id):
            rows = session.query(EntityTagEntity).filter_by(user_id=user_id).all()
            counts: dict[str, int] = {}
            for row in rows:
                counts[row.tag] = counts.get(row.tag, 0) + 1
            return sorted(counts.items())
        rows = session.query(EntityTagEntity.tag, func.count(EntityTagEntity.id)).filter_by(
            user_id=user_id
        ).group_by(EntityTagEntity.tag).order_by(EntityTagEntity.tag).all()
        return [(row[0], row[1]) for row in rows]


def delete_for_entity_locked(session, user_id: int, entity_type: str, entity_id: str) -> int:
    """Delete one entity's tags inside a caller transaction holding the owner lock."""
    return session.query(EntityTagEntity).filter_by(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id
    ).delete()


def delete_for_entity(user_id: int, entity_type: str, entity_id: str) -> int:
    """Delete all tags for one entity (call from that entity's delete path). Returns rows deleted."""
    with get_db() as session:
        vocabulary_repo.lock_owner(session, user_id)
        return delete_for_entity_locked(session, user_id, entity_type, entity_id)


def memberships_for(user_id: int, entity_type: str, entity_ids: List[str]) -> dict:
    """Exact tags for the given ids of one type. Missing ids are omitted."""
    if not entity_ids:
        return {}
    with get_db() as session:
        from storage.crypto.query import active
        if active(session, user_id):
            loaded = session.query(EntityTagEntity).filter(
                EntityTagEntity.user_id == user_id,
                EntityTagEntity.entity_type == entity_type,
                EntityTagEntity.entity_id.in_(list(entity_ids)),
            ).all()
            rows = [(row.entity_id, row.tag) for row in loaded]
        else:
            rows = session.query(EntityTagEntity.entity_id, EntityTagEntity.tag).filter(
                EntityTagEntity.user_id == user_id,
                EntityTagEntity.entity_type == entity_type,
                EntityTagEntity.entity_id.in_(list(entity_ids)),
            ).all()
    grouped = {entity_id: [] for entity_id in entity_ids}
    for entity_id, tag in rows:
        grouped.setdefault(entity_id, []).append(tag)
    return {entity_id: sorted(set(tags)) for entity_id, tags in grouped.items() if tags}


def ids_for_exact_tag(
    user_id: int, entity_type: str, tag: str, *, cursor: Optional[str], limit: int
) -> List[str]:
    """Distinct ids holding this exact tag, ordered by id, strictly after `cursor`."""
    tag = normalize_tag(tag)
    if not tag:
        return []
    with get_db() as session:
        query = session.query(EntityTagEntity.entity_id).filter_by(
            user_id=user_id, entity_type=entity_type, tag=tag
        )
        if cursor is not None:
            query = query.filter(EntityTagEntity.entity_id > cursor)
        rows = query.distinct().order_by(EntityTagEntity.entity_id).limit(limit).all()
    return [row.entity_id for row in rows]
