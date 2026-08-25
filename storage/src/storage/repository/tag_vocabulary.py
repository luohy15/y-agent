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

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.tag_vocabulary import TagVocabularyEntity


def ensure(session, user_id: int, tag: str) -> bool:
    """Insert a vocabulary row for (user_id, tag) if missing. Returns True if created.

    Session-scoped: callers already inside a transaction pass their own
    session so this registers atomically with their own write. Race-safe via
    ON CONFLICT DO NOTHING on PostgreSQL; SQLite (tests) uses a nested
    savepoint and catches the IntegrityError instead, since SQLite lacks a
    portable multi-column upsert through this SQLAlchemy version pin.
    """
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
