"""Function-based tag_vocabulary repository.

tag_vocabulary is a durable, owner-scoped canonical tag registry keyed by
(user_id, tag) (todo 3290). Unlike entity_tag (a usage projection), a row
here can exist with zero uses. `ensure()` is the session-scoped, race-safe
upsert both `create()` and the entity_tag write paths (add_tag/sync_tags in
storage.repository.entity_tag) call, so every normalized tag write registers
vocabulary atomically with its carrier write rather than needing a second,
separately-committed transaction.
"""

from typing import Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.tag_vocabulary import TagVocabularyEntity
from storage.entity.entity_tag import EntityTagEntity


class TagVocabularyConflict(ValueError):
    """Vocabulary retirement was rejected because raw memberships still exist."""


def lock_owner(session, user_id: int) -> None:
    """Serialize vocabulary retirement and membership writers until commit.

    PostgreSQL two-integer advisory namespace 3397 is reserved for tag owners;
    the second key is the internal owner ID. SQLite is for outcome tests only.
    Call before membership/existence reads, not merely before inserting rows.
    """
    if session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(3397, :owner_id)"),
            {"owner_id": user_id},
        )


def delete_empty(user_id: int, tag: str) -> None:
    """Delete only an existing, unused exact vocabulary spelling for this owner."""
    with get_db() as session:
        lock_owner(session, user_id)
        row = session.query(TagVocabularyEntity).filter_by(user_id=user_id, tag=tag).first()
        if row is None:
            raise LookupError("Tag is not in the vocabulary")
        if session.query(EntityTagEntity.id).filter_by(user_id=user_id, tag=tag).first():
            raise TagVocabularyConflict("Tag still has associated carriers")
        session.delete(row)


def ensure(session, user_id: int, tag: str) -> bool:
    """Insert a vocabulary row for (user_id, tag) if missing. Returns True if created.

    Session-scoped: callers already inside a transaction pass their own
    session so this registers atomically with their own write. Race-safe via
    ON CONFLICT DO NOTHING on PostgreSQL; SQLite (tests) uses a nested
    savepoint and catches the IntegrityError instead, since SQLite lacks a
    portable multi-column upsert through this SQLAlchemy version pin.
    """
    lock_owner(session, user_id)
    table = TagVocabularyEntity.__table__
    if session.bind.dialect.name == "postgresql":
        statement = pg_insert(table).values(user_id=user_id, tag=tag).on_conflict_do_nothing(
            index_elements=("user_id", "tag")
        ).returning(table.c.id)
        return session.execute(statement).scalar_one_or_none() is not None
    try:
        with session.begin_nested():
            session.add(TagVocabularyEntity(user_id=user_id, tag=tag))
            session.flush()
        return True
    except IntegrityError:
        return False


def create(user_id: int, tag: str) -> Tuple[str, bool]:
    """Idempotently register one canonical tag in its own transaction.

    `tag` must already be normalized and syntax-validated by the caller
    (storage.service.tag.create_vocabulary); this function only owns the
    uniqueness race. Returns (tag, created).
    """
    with get_db() as session:
        created = ensure(session, user_id, tag)
        return tag, created
