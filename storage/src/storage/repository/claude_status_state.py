"""Claude status incident dedup state repository."""

from typing import Optional

from storage.database.base import get_db
from storage.entity.claude_status_state import ClaudeStatusStateEntity
from storage.util import get_utc_iso8601_timestamp


def get_state(user_id: int, incident_guid: str) -> Optional[ClaudeStatusStateEntity]:
    with get_db() as session:
        return (
            session.query(ClaudeStatusStateEntity)
            .filter_by(user_id=user_id, incident_guid=incident_guid)
            .first()
        )


def upsert_state(
    user_id: int,
    incident_guid: str,
    title: str,
    status: str,
) -> dict:
    """Insert or update the state row. Returns a dict snapshot of the row."""
    now = get_utc_iso8601_timestamp()
    with get_db() as session:
        row = (
            session.query(ClaudeStatusStateEntity)
            .filter_by(user_id=user_id, incident_guid=incident_guid)
            .first()
        )
        if row is None:
            row = ClaudeStatusStateEntity(
                user_id=user_id,
                incident_guid=incident_guid,
                title=title,
                status=status,
                first_seen_at=now,
                last_updated_at=now,
            )
            session.add(row)
        else:
            row.title = title
            row.status = status
            row.last_updated_at = now
        session.flush()
        return {
            "user_id": row.user_id,
            "incident_guid": row.incident_guid,
            "title": row.title,
            "status": row.status,
            "first_seen_at": row.first_seen_at,
            "last_updated_at": row.last_updated_at,
            "notified_at": row.notified_at,
            "resolved_notified_at": row.resolved_notified_at,
        }


def mark_notified(user_id: int, incident_guid: str) -> None:
    now = get_utc_iso8601_timestamp()
    with get_db() as session:
        row = (
            session.query(ClaudeStatusStateEntity)
            .filter_by(user_id=user_id, incident_guid=incident_guid)
            .first()
        )
        if row:
            row.notified_at = now


def mark_resolved_notified(user_id: int, incident_guid: str) -> None:
    now = get_utc_iso8601_timestamp()
    with get_db() as session:
        row = (
            session.query(ClaudeStatusStateEntity)
            .filter_by(user_id=user_id, incident_guid=incident_guid)
            .first()
        )
        if row:
            row.resolved_notified_at = now
