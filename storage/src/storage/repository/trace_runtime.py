"""Owner-scoped runtime evidence (todo 4070).

`trace_runtime_snapshot` is worker-written. Reads serve the todo list and the
watchdog decision; the only writer is `refresh_trace_runtime`.
"""

from typing import Dict, Iterable, Optional, Set, Tuple

from sqlalchemy import and_, case, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.trace_runtime_snapshot import TraceRuntimeSnapshotEntity
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


def upsert_snapshot(user_id: int, observed_at_unix: int, ok: bool, jobs: Dict[str, list]) -> None:
    """Write one probe result, never replacing newer evidence.

    Monotonic on `observed_at_unix`: an older or concurrent pass is a no-op.
    """
    table = TraceRuntimeSnapshotEntity.__table__
    now_iso = get_utc_iso8601_timestamp()
    now_unix = get_unix_timestamp()
    values = {
        "user_id": user_id,
        "observed_at_unix": observed_at_unix,
        "ok": ok,
        "jobs": jobs,
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_at_unix": now_unix,
        "updated_at_unix": now_unix,
    }
    with get_db() as session:
        if session.get_bind().dialect.name == "postgresql":
            insert = pg_insert(table).values(**values)
            statement = insert.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "observed_at_unix": observed_at_unix,
                    "ok": ok,
                    "jobs": jobs,
                    "updated_at": now_iso,
                    "updated_at_unix": now_unix,
                },
                where=insert.excluded.observed_at_unix >= table.c.observed_at_unix,
            )
            session.execute(statement)
            return
        row = session.query(TraceRuntimeSnapshotEntity).filter_by(user_id=user_id).first()
        if row is None:
            session.add(TraceRuntimeSnapshotEntity(**values))
        elif row.observed_at_unix <= observed_at_unix:
            row.observed_at_unix = observed_at_unix
            row.ok = ok
            row.jobs = jobs
            row.updated_at = now_iso
            row.updated_at_unix = now_unix


def get_snapshots(session, user_ids: Iterable[int]) -> Dict[int, dict]:
    """Probe rows keyed by owner; an owner with no row is omitted."""
    user_ids = set(user_ids)
    if not user_ids:
        return {}
    rows = (session.query(TraceRuntimeSnapshotEntity)
            .filter(TraceRuntimeSnapshotEntity.user_id.in_(user_ids)).all())
    return {
        row.user_id: {
            "ok": row.ok,
            "observed_at_unix": row.observed_at_unix,
            "jobs": row.jobs,
        }
        for row in rows
    }


def trace_runtime_roles(session, user_ids: Iterable[int], trace_ids: Iterable[str]) -> Dict[Tuple[int, str], Tuple[int, int, int, int]]:
    """Chat evidence per (owner, trace): `(chat_count, running_topic,
    running_topicless, topic_chats)` in one grouped read.

    `running_topic` / `running_topicless` are SQL-running chats with / without a
    topic. `topic_chats` counts every chat that has a topic, so a running
    topic-less chat on a trace that also has a coordinator reads as a child.
    """
    user_ids, trace_ids = set(user_ids), set(trace_ids)
    if not user_ids or not trace_ids:
        return {}
    has_topic = and_(ChatEntity.topic.isnot(None), ChatEntity.topic != "")
    no_topic = or_(ChatEntity.topic.is_(None), ChatEntity.topic == "")
    rows = (
        session.query(
            ChatEntity.user_id,
            ChatEntity.trace_id,
            func.count(ChatEntity.id),
            func.sum(case((and_(ChatEntity.status == "running", has_topic), 1), else_=0)),
            func.sum(case((and_(ChatEntity.status == "running", no_topic), 1), else_=0)),
            func.sum(case((has_topic, 1), else_=0)),
        )
        .filter(ChatEntity.user_id.in_(user_ids), ChatEntity.trace_id.in_(trace_ids))
        .group_by(ChatEntity.user_id, ChatEntity.trace_id)
        .all()
    )
    return {
        (row[0], row[1]): (int(row[2] or 0), int(row[3] or 0), int(row[4] or 0), int(row[5] or 0))
        for row in rows
    }
