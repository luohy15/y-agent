"""Normal-session-end dispositions (todo 4077).

`trace_session_end` is worker-written only. The insert is idempotent on
`(user_id, chat_id, run_key)`, so a duplicate closeout records nothing new.
"""

from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from storage.database.base import get_db
from storage.entity.trace_session_end import TraceSessionEndEntity
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


def insert_disposition(user_id: int, chat_id: str, trace_id: str, run_key: str, *,
                       disposition: str, evidence: Optional[str] = None,
                       runtime_observed_at_unix: Optional[int] = None,
                       ended_at_unix: Optional[int] = None) -> bool:
    """Record one reconcile outcome; returns False when the run already has a row."""
    now_iso = get_utc_iso8601_timestamp()
    now_unix = get_unix_timestamp()
    values = {
        "user_id": user_id,
        "chat_id": chat_id,
        "trace_id": trace_id,
        "run_key": run_key,
        "ended_at_unix": ended_at_unix if ended_at_unix is not None else now_unix,
        "disposition": disposition,
        "evidence": evidence,
        "runtime_observed_at_unix": runtime_observed_at_unix,
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_at_unix": now_unix,
        "updated_at_unix": now_unix,
    }
    with get_db() as session:
        if session.get_bind().dialect.name == "postgresql":
            statement = pg_insert(TraceSessionEndEntity.__table__).values(**values)
            result = session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=["user_id", "chat_id", "run_key"],
                )
            )
            return bool(result.rowcount)
        existing = (session.query(TraceSessionEndEntity.id)
                    .filter_by(user_id=user_id, chat_id=chat_id, run_key=run_key)
                    .first())
        if existing is not None:
            return False
        session.add(TraceSessionEndEntity(**values))
        return True
