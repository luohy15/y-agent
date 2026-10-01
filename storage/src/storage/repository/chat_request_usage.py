"""Repository for per-request transcript usage rows.

A batch folds to one write per request id, then lands in a few statements:
one advisory lock, one identity read, one multi-row insert, and a conflict
re-read only when the insert predicate refuses a key. A repeated request id
whose session, chat and model all match merges its counters in. A repeated id
where any of those three differs is left untouched and reported per field.
The check and the write share one lock, so two concurrent writers cannot both
decide the row is new and then merge into each other.
"""

from sqlalchemy import Integer, String, bindparam, case, func, literal, select, text
from sqlalchemy.dialects.postgresql import ARRAY
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


def _identity(row: dict) -> tuple:
    return (row["session_id"], row["chat_id"], row["model"])


def _larger(left, right):
    """The larger present counter. A NULL never replaces a present value."""
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right


def _merge_pending(pending: dict, row: dict) -> None:
    for name in COUNTERS:
        pending[name] = _larger(pending.get(name), row.get(name))
    if row["usage_state"] == "observed":
        pending["usage_state"] = "observed"
    pending["requested_at"] = row["requested_at"]


def _add_conflicts(totals: dict, left: tuple, right: tuple, times: int = 1) -> None:
    totals["session"] += (left[0] != right[0]) * times
    totals["chat"] += (left[1] != right[1]) * times
    totals["model"] += (left[2] != right[2]) * times


# One statement, one array bind. ORDER BY is on this statement: the lock is
# taken as rows are projected, so overlapping batches lock in the same order.
_LOCK_REQUESTS = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(key, 0)) "
    "FROM unnest(CAST(:keys AS text[])) AS key "
    "ORDER BY key"
).bindparams(bindparam("keys", type_=ARRAY(String())))


def _lock_requests(session, dialect: str, user_id: int, request_ids) -> None:
    """Serialize writers for these (owner, request id) keys until commit.

    PostgreSQL takes one transaction advisory lock per key, in sorted key
    order, so two overlapping batches cannot deadlock. SQLite allows one
    writer at a time for the whole database, so no extra lock is needed.
    """
    if dialect != "postgresql":
        return
    keys = sorted({f"{user_id}|{request_id}" for request_id in request_ids})
    if not keys:
        return
    session.execute(_LOCK_REQUESTS, {"keys": keys})


def _stored_identities(session, user_id: int, request_ids) -> dict:
    if not request_ids:
        return {}
    found = session.execute(
        select(
            ChatRequestUsageEntity.request_id,
            ChatRequestUsageEntity.session_id,
            ChatRequestUsageEntity.chat_id,
            ChatRequestUsageEntity.model,
        ).where(
            ChatRequestUsageEntity.user_id == user_id,
            ChatRequestUsageEntity.request_id.in_(list(request_ids)),
        )
    ).all()
    return {row.request_id: (row.session_id, row.chat_id, row.model) for row in found}


def _fold_group(stored: tuple | None, group: list[dict], conflicts: dict):
    """One write for this request id, and how many original rows it accepts.

    The stored identity, or the first row when nothing is stored, wins. A later
    row that matches it merges in (max counters, observed wins, last
    requested_at) and counts as accepted again. A later row that differs counts
    as a conflict and is not written. One insert cannot touch a key twice.
    """
    effective = stored
    pending = None
    accepted = 0
    for row in group:
        ident = _identity(row)
        if effective is None:
            effective = ident
            pending = dict(row)
            accepted += 1
            continue
        if ident == effective:
            if pending is None:
                pending = dict(row)
            else:
                _merge_pending(pending, row)
            accepted += 1
        else:
            _add_conflicts(conflicts, effective, ident)
    return pending, accepted


# Same merge as `_greatest` / `_observed`. A SQLAlchemy VALUES list compiles one
# bind per cell, which costs more than the round trip at a few hundred rows, so
# PostgreSQL sends one array per column instead.
_PG_UPSERT = text(
    """
    INSERT INTO chat_request_usage (
        user_id, request_id, session_id, chat_id, model, requested_at,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        usage_state, created_at, updated_at, created_at_unix, updated_at_unix
    )
    SELECT
        :user_id, request_id, session_id, chat_id, model, requested_at,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        usage_state, :stamp, :stamp, :stamp_unix, :stamp_unix
    FROM unnest(
        CAST(:request_id AS text[]),
        CAST(:session_id AS text[]),
        CAST(:chat_id AS text[]),
        CAST(:model AS text[]),
        CAST(:requested_at AS text[]),
        CAST(:input_tokens AS int[]),
        CAST(:output_tokens AS int[]),
        CAST(:cache_creation_tokens AS int[]),
        CAST(:cache_read_tokens AS int[]),
        CAST(:usage_state AS text[])
    ) AS incoming(
        request_id, session_id, chat_id, model, requested_at,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        usage_state
    )
    ON CONFLICT (user_id, request_id) DO UPDATE SET
        input_tokens = GREATEST(
            COALESCE(chat_request_usage.input_tokens, EXCLUDED.input_tokens),
            COALESCE(EXCLUDED.input_tokens, chat_request_usage.input_tokens)),
        output_tokens = GREATEST(
            COALESCE(chat_request_usage.output_tokens, EXCLUDED.output_tokens),
            COALESCE(EXCLUDED.output_tokens, chat_request_usage.output_tokens)),
        cache_creation_tokens = GREATEST(
            COALESCE(chat_request_usage.cache_creation_tokens, EXCLUDED.cache_creation_tokens),
            COALESCE(EXCLUDED.cache_creation_tokens, chat_request_usage.cache_creation_tokens)),
        cache_read_tokens = GREATEST(
            COALESCE(chat_request_usage.cache_read_tokens, EXCLUDED.cache_read_tokens),
            COALESCE(EXCLUDED.cache_read_tokens, chat_request_usage.cache_read_tokens)),
        usage_state = CASE
            WHEN chat_request_usage.usage_state = 'observed'
              OR EXCLUDED.usage_state = 'observed'
            THEN 'observed' ELSE 'missing' END,
        requested_at = EXCLUDED.requested_at,
        updated_at = :stamp,
        updated_at_unix = :stamp_unix
    WHERE chat_request_usage.session_id = EXCLUDED.session_id
      AND chat_request_usage.chat_id = EXCLUDED.chat_id
      AND chat_request_usage.model = EXCLUDED.model
    RETURNING request_id
    """
).bindparams(
    bindparam("request_id", type_=ARRAY(String())),
    bindparam("session_id", type_=ARRAY(String())),
    bindparam("chat_id", type_=ARRAY(String())),
    bindparam("model", type_=ARRAY(String())),
    bindparam("requested_at", type_=ARRAY(String())),
    bindparam("usage_state", type_=ARRAY(String())),
    bindparam("input_tokens", type_=ARRAY(Integer())),
    bindparam("output_tokens", type_=ARRAY(Integer())),
    bindparam("cache_creation_tokens", type_=ARRAY(Integer())),
    bindparam("cache_read_tokens", type_=ARRAY(Integer())),
)


def _write_rows_pg(session, user_id: int, rows: list[dict]) -> set:
    stamp = get_utc_iso8601_timestamp()
    written = session.execute(
        _PG_UPSERT,
        {
            "user_id": user_id,
            "stamp": stamp,
            "stamp_unix": get_unix_timestamp(),
            "request_id": [row["request_id"] for row in rows],
            "session_id": [row["session_id"] for row in rows],
            "chat_id": [row["chat_id"] for row in rows],
            "model": [row["model"] for row in rows],
            "requested_at": [row["requested_at"] for row in rows],
            "usage_state": [row["usage_state"] for row in rows],
            **{name: [row.get(name) for row in rows] for name in COUNTERS},
        },
    ).all()
    return {row[0] for row in written}


def _write_rows(session, dialect: str, user_id: int, rows: list[dict]) -> set:
    if not rows:
        return set()
    if dialect == "postgresql":
        return _write_rows_pg(session, user_id, rows)
    insert = sqlite_insert(ChatRequestUsageEntity).values(
        [_values(user_id, row) for row in rows]
    )
    excluded = insert.excluded
    stored = ChatRequestUsageEntity
    same_identity = (
        (stored.session_id == excluded.session_id)
        & (stored.chat_id == excluded.chat_id)
        & (stored.model == excluded.model)
    )
    merge = {
        name: _greatest(dialect, getattr(stored, name), getattr(excluded, name))
        for name in COUNTERS
    }
    written = session.execute(
        insert.on_conflict_do_update(
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
        ).returning(stored.request_id)
    ).all()
    return {row[0] for row in written}


def _apply(session, user_id: int, row: dict) -> dict:
    """Write one row and report what happened to it.

    The lock is taken before reading the stored identity, and the insert's
    conflict clause repeats the same condition: it merges only when the stored
    session, chat and model all match. A conflict writes nothing. Because the
    lock is held until commit, a second writer blocks until it can see the
    first writer's row, so it counts the conflict instead of merging into it.
    """
    dialect = session.get_bind().dialect.name
    _lock_requests(session, dialect, user_id, [row["request_id"]])

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

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["request_id"], []).append(row)

    with get_db() as session:
        dialect = session.get_bind().dialect.name
        _lock_requests(session, dialect, user_id, list(groups))
        stored = _stored_identities(session, user_id, list(groups))
        pending = []
        accepted_by_id = {}
        for request_id, group in groups.items():
            folded, count = _fold_group(stored.get(request_id), group, conflicts)
            if folded is not None:
                pending.append(folded)
                accepted_by_id[request_id] = count
        written = _write_rows(session, dialect, user_id, pending)
        missing = [row for row in pending if row["request_id"] not in written]
        if missing:
            fresh = _stored_identities(
                session, user_id, [row["request_id"] for row in missing]
            )
            for row in missing:
                # The predicate refused the merge: another writer stored a
                # different identity after the pre-read (or the lock was not
                # taken). Every folded row shared the identity we tried to write.
                ident = fresh.get(row["request_id"])
                times = accepted_by_id[row["request_id"]]
                if ident is None or ident == _identity(row):
                    accepted += times
                else:
                    _add_conflicts(conflicts, ident, _identity(row), times)
        for request_id in written:
            accepted += accepted_by_id[request_id]
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
