"""Admission rows keyed by normalized email. No user-table derivation."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.user_access import UserAccessEntity
from storage.util import format_utc_iso8601, get_unix_timestamp, get_utc_iso8601_timestamp

MAX_NOTIFICATION_ATTEMPTS = 10
MIN_ATTEMPT_GAP_MS = 60_000
STALE_CLAIM_MS = 120_000


def _now() -> str:
    return get_utc_iso8601_timestamp()


def _before(milliseconds: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(milliseconds=milliseconds)
    return format_utc_iso8601(moment)


def _touch(row: UserAccessEntity, now: str) -> None:
    row.updated_at = now
    row.updated_at_unix = get_unix_timestamp()


def _public(row: UserAccessEntity) -> dict:
    return {
        "email": row.email,
        "status": row.status,
        "source": row.source,
        "first_requested_at": row.first_requested_at,
        "last_requested_at": row.last_requested_at,
        "request_count": row.request_count,
        "decided_at": row.decided_at,
        "decided_by": row.decided_by,
        "notification_status": row.notification_status,
        "notification_attempts": row.notification_attempts,
        "notified_at": row.notified_at,
        "notification_claimed_at": row.notification_claimed_at,
        "last_notification_attempt_at": row.last_notification_attempt_at,
        "last_notification_error": row.last_notification_error,
    }


def get_by_email(email: str) -> Optional[dict]:
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).one_or_none()
        return _public(row) if row else None


def list_applications(status: Optional[str] = None) -> list[dict]:
    with get_db() as session:
        query = session.query(UserAccessEntity)
        if status:
            query = query.filter(UserAccessEntity.status == status)
        rows = query.order_by(UserAccessEntity.last_requested_at.desc().nullslast(), UserAccessEntity.email.asc()).all()
        return [_public(row) for row in rows]


def list_all() -> list[dict]:
    with get_db() as session:
        rows = session.query(UserAccessEntity).all()
        return [_public(row) for row in rows]


def bump_request(email: str) -> Optional[dict]:
    now = _now()
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None:
            return None
        row.last_requested_at = now
        row.request_count = int(row.request_count or 0) + 1
        _touch(row, now)
        session.flush()
        return _public(row)


def insert_pending(email: str) -> bool:
    now = _now()
    unix = get_unix_timestamp()
    with get_db() as session:
        row = UserAccessEntity(
            email=email,
            status="pending",
            source="waitlist",
            first_requested_at=now,
            last_requested_at=now,
            request_count=1,
            notification_status="pending",
            notification_attempts=0,
            created_at=now,
            updated_at=now,
            created_at_unix=unix,
            updated_at_unix=unix,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return False
        return True


def ensure_rollout(email: str) -> str:
    """Insert or approve one explicit rollout identity. Never reads the user table."""
    now = _now()
    unix = get_unix_timestamp()
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None:
            session.add(UserAccessEntity(
                email=email,
                status="approved",
                source="rollout",
                request_count=0,
                decided_at=now,
                decided_by="rollout",
                notification_status="skipped",
                notification_attempts=0,
                created_at=now,
                updated_at=now,
                created_at_unix=unix,
                updated_at_unix=unix,
            ))
            session.flush()
            return "inserted"
        if row.status == "approved":
            return "present"
        row.status = "approved"
        row.decided_at = now
        row.decided_by = "rollout"
        if row.notification_status == "pending":
            row.notification_status = "skipped"
        _touch(row, now)
        session.flush()
        return "approved"


def approve(email: str, decided_by: str) -> Optional[tuple[dict, bool]]:
    now = _now()
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None:
            return None
        if row.status == "approved":
            return _public(row), False
        row.status = "approved"
        row.decided_at = now
        row.decided_by = decided_by
        if row.notification_status == "pending":
            row.notification_status = "skipped"
        _touch(row, now)
        session.flush()
        return _public(row), True


def list_due_notice_emails() -> list[str]:
    stale_before = _before(STALE_CLAIM_MS)
    gap_before = _before(MIN_ATTEMPT_GAP_MS)
    with get_db() as session:
        rows = session.query(UserAccessEntity.email).filter(
            or_(
                and_(
                    UserAccessEntity.notification_status == "pending",
                    UserAccessEntity.notification_attempts < MAX_NOTIFICATION_ATTEMPTS,
                    or_(
                        UserAccessEntity.last_notification_attempt_at.is_(None),
                        UserAccessEntity.last_notification_attempt_at <= gap_before,
                    ),
                ),
                and_(
                    UserAccessEntity.notification_status == "sending",
                    UserAccessEntity.notification_claimed_at.isnot(None),
                    UserAccessEntity.notification_claimed_at <= stale_before,
                ),
            )
        ).all()
        return [row.email for row in rows]


def claim_notice(email: str) -> Optional[dict]:
    now = _now()
    stale_before = _before(STALE_CLAIM_MS)
    gap_before = _before(MIN_ATTEMPT_GAP_MS)
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None:
            return None
        if row.notification_status == "pending":
            if int(row.notification_attempts or 0) >= MAX_NOTIFICATION_ATTEMPTS:
                row.notification_status = "failed"
                _touch(row, now)
                return None
            last_attempt = row.last_notification_attempt_at
            if last_attempt and last_attempt > gap_before:
                return None
        elif row.notification_status == "sending":
            claimed = row.notification_claimed_at or ""
            if not claimed or claimed > stale_before:
                return None
        else:
            return None
        if row.status == "approved":
            row.notification_status = "skipped"
            row.notification_claimed_at = None
            _touch(row, now)
            return None
        row.notification_status = "sending"
        row.notification_claimed_at = now
        _touch(row, now)
        session.flush()
        return _public(row)


def mark_notice_sent(email: str) -> None:
    now = _now()
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None or row.notification_status != "sending":
            return
        row.notification_status = "sent"
        row.notified_at = now
        row.last_notification_error = None
        _touch(row, now)


def mark_notice_attempt_failed(email: str, error: str) -> Optional[str]:
    now = _now()
    with get_db() as session:
        row = session.query(UserAccessEntity).filter_by(email=email).with_for_update().one_or_none()
        if row is None or row.notification_status != "sending":
            return None
        attempts = int(row.notification_attempts or 0) + 1
        row.notification_attempts = attempts
        row.last_notification_attempt_at = now
        row.last_notification_error = error
        row.notification_claimed_at = None
        if row.status == "approved":
            row.notification_status = "skipped"
        else:
            row.notification_status = "failed" if attempts >= MAX_NOTIFICATION_ATTEMPTS else "pending"
        _touch(row, now)
        session.flush()
        return row.notification_status
