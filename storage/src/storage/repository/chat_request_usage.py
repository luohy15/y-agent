"""Repository for per-request transcript usage rows.

The merge rule is one statement per row. A repeated request id whose session,
chat and model all match merges its counters in. A repeated id where any of
those three differs is left untouched and reported per field. The check and
the write share one lock, so two concurrent writers cannot both decide the row
is new and then merge into each other.
"""

from sqlalchemy import case, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from storage.database.base import get_db
from storage.entity.chat_request_usage import ChatRequestUsageEntity
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
)


def _present(column, incoming):
    """Each side with NULL replaced by the other side, so a missing counter
    never takes part in the comparison. Both NULL stays NULL."""
    return func.coalesce(column, incoming), func.coalesce(incoming, column)


def _greatest(dialect: str, column, incoming):
    """The larger present value. A NULL never erases a stored counter.

    PostgreSQL GREATEST ignores NULL arguments, but SQLite's scalar MAX returns
    NULL when any argument is NULL, which would wipe a counter a later partial
    record simply omitted. Each side falls back to the other first, so both
    dialects behave the same: a present value beats NULL, and two present
    values keep the larger one.
    """
    stored_side, incoming_side = _present(column, incoming)
    if dialect == "postgresql":
        return func.greatest(stored_side, incoming_side)
    return func.max(stored_side, incoming_side)


def _observed(existing, incoming):
    """`observed` when either side saw a usable usage dict, else `missing`.

    The two state strings do not sort into that order, so the rule is spelled
    out rather than taken from a comparison.
    """
    return case(
        ((existing == "observed") | (incoming == "observed"), literal("observed")),
        else_=literal("missing"),
    )


def _values(user_id: int, row: dict) -> dict:
    return {
        "user_id": user_id,
        "request_id": row["request_id"],
        "session_id": row["session_id"],
        "chat_id": row["chat_id"],
        "model": row["model"],
        "requested_at": row["requested_at"],
        "usage_state": row["usage_state"],
        **{name: row.get(name) for name in COUNTERS},
    }


def _identity_conflict(existing: ChatRequestUsageEntity, row: dict) -> dict:
    return {
        "session": int(existing.session_id != row["session_id"]),
        "chat": int(existing.chat_id != row["chat_id"]),
        "model": int(existing.model != row["model"]),
    }


def _lock_request(session, dialect: str, user_id: int, request_id: str) -> None:
    """Serialize writers for one (owner, request id) until this transaction ends.

    PostgreSQL takes a transaction advisory lock, released on commit or
    rollback. SQLite allows one writer at a time for the whole database, so
    two upserts cannot interleave there and no extra lock is needed.
    """
    if dialect != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{user_id}|{request_id}"},
    )


def _apply(session, user_id: int, row: dict) -> dict:
    """Write one row and report what happened to it.

    The lock is taken before reading the stored identity, and the insert's
    conflict clause repeats the same condition: it merges only when the stored
    session, chat and model all match. A conflict writes nothing. Because the
    lock is held until commit, a second writer blocks until it can see the
    first writer's row, so it counts the conflict instead of merging into it.
    """
    dialect = session.get_bind().dialect.name
    _lock_request(session, dialect, user_id, row["request_id"])

    existing = session.execute(
        select(ChatRequestUsageEntity)
        .where(
            ChatRequestUsageEntity.user_id == user_id,
            ChatRequestUsageEntity.request_id == row["request_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        conflict = _identity_conflict(existing, row)
        if any(conflict.values()):
            return {"accepted": False, "conflicts": conflict}

    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert(ChatRequestUsageEntity).values(**_values(user_id, row))
    excluded = stmt.excluded
    stored = ChatRequestUsageEntity
    same_identity = (
        (stored.session_id == excluded.session_id)
        & (stored.chat_id == excluded.chat_id)
        & (stored.model == excluded.model)
    )
    merge = {name: _greatest(dialect, getattr(stored, name), getattr(excluded, name)) for name in COUNTERS}
    written = session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "request_id"],
            set_={
                **merge,
                "usage_state": _observed(stored.usage_state, excluded.usage_state),
                "requested_at": excluded.requested_at,
                # A conflict-clause update skips ORM onupdate hooks.
                "updated_at": get_utc_iso8601_timestamp(),
                "updated_at_unix": get_unix_timestamp(),
            },
            where=same_identity,
        ).returning(stored.id)
    ).first()
    if written is None:
        # The conflict predicate refused the merge: another writer stored a
        # different identity first. Report it the same way as above.
        session.expire_all()
        existing = session.execute(
            select(ChatRequestUsageEntity).where(
                ChatRequestUsageEntity.user_id == user_id,
                ChatRequestUsageEntity.request_id == row["request_id"],
            )
        ).scalar_one()
        return {"accepted": False, "conflicts": _identity_conflict(existing, row)}
    return {"accepted": True, "conflicts": {"session": 0, "chat": 0, "model": 0}}


def upsert_rows(user_id: int, rows: list[dict]) -> dict:
    """Insert or merge each row. Returns accepted and per-field conflict counts.

    `accepted` counts rows newly inserted or merged. A row whose stored
    session, chat or model differs is not written; each differing field is
    counted on its own, so one row can add to more than one counter.
    """
    accepted = 0
    conflicts = {"session": 0, "chat": 0, "model": 0}
    if not rows:
        return {"accepted": accepted, "conflicts": conflicts}

    with get_db() as session:
        for row in rows:
            outcome = _apply(session, user_id, row)
            if outcome["accepted"]:
                accepted += 1
            for field in conflicts:
                conflicts[field] += outcome["conflicts"][field]
    return {"accepted": accepted, "conflicts": conflicts}


def rows_for_chats(user_id: int, chat_ids: list[str]) -> list[ChatRequestUsageEntity]:
    """Every usage row belonging to these chats, for one owner."""
    if not chat_ids:
        return []
    with get_db() as session:
        return list(session.scalars(
            select(ChatRequestUsageEntity)
            .where(
                ChatRequestUsageEntity.user_id == user_id,
                ChatRequestUsageEntity.chat_id.in_(chat_ids),
            )
        ).all())


def turns_for_chats(user_id: int, chat_ids: list[str]) -> dict[str, int]:
    """Answered turns per chat, summed across the derived daily activity rows."""
    if not chat_ids:
        return {}
    from storage.entity.chat_model_activity import ChatModelActivityEntity

    with get_db() as session:
        grouped = session.execute(
            select(
                ChatModelActivityEntity.chat_id,
                func.coalesce(func.sum(ChatModelActivityEntity.turns), 0),
            )
            .where(
                ChatModelActivityEntity.user_id == user_id,
                ChatModelActivityEntity.chat_id.in_(chat_ids),
            )
            .group_by(ChatModelActivityEntity.chat_id)
        ).all()
    return {chat_id: int(turns) for chat_id, turns in grouped}
