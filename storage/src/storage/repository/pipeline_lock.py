"""Pipeline lock repository — prevents overlapping scheduled runs."""

from datetime import datetime, timezone, timedelta
from typing import Optional

from storage.entity.pipeline_lock import PipelineLockEntity
from storage.database.base import get_db
from storage.util import get_utc_iso8601_timestamp


def _parse_iso8601(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def try_acquire_lock(action: str, ttl_seconds: int = 840) -> bool:
    """Try to acquire a lock for a pipeline action.

    Returns True if the lock was acquired (either no existing lock or the
    existing one has expired), False if another invocation is still running.
    Fails open on DB errors so the pipeline is not blocked.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ttl_seconds)
    now_iso = get_utc_iso8601_timestamp()
    try:
        with get_db() as session:
            lock = session.query(PipelineLockEntity).filter_by(action=action).first()
            if lock is None:
                session.add(PipelineLockEntity(action=action, locked_at=now_iso))
                return True
            locked_at = _parse_iso8601(lock.locked_at)
            if locked_at is None or locked_at < cutoff:
                lock.locked_at = now_iso
                return True
            return False
    except Exception:
        return True


def release_lock(action: str) -> None:
    """Release a lock by setting locked_at to the epoch."""
    try:
        with get_db() as session:
            lock = session.query(PipelineLockEntity).filter_by(action=action).first()
            if lock:
                lock.locked_at = "2000-01-01T00:00:00.000Z"
    except Exception:
        pass


def is_locked(action: str, ttl_seconds: int = 840) -> bool:
    """Return True if a live (non-expired) lock exists for this action."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
    with get_db() as session:
        lock = session.query(PipelineLockEntity).filter_by(action=action).first()
        if lock is None:
            return False
        locked_at = _parse_iso8601(lock.locked_at)
        if locked_at is None:
            return False
        return locked_at >= cutoff
