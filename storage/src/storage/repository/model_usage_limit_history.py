"""Function-based repository for subscription limit-window history (todo 3717).

One transaction writes the attempt and its observations. A retried write of
the same attempt_id is a no-op (ON CONFLICT DO NOTHING on both tables).
Range reads have no LIMIT: the service refuses an oversized range before it
asks, rather than silently truncating here.
"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.entity.model_usage_limit_attempt import ModelUsageLimitAttemptEntity
from storage.entity.model_usage_limit_observation import ModelUsageLimitObservationEntity
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


def _attempt_values(row: dict) -> dict:
    now = get_utc_iso8601_timestamp()
    unix = get_unix_timestamp()
    return dict(
        attempt_id=row["attempt_id"],
        user_id=row["user_id"],
        attempted_at=row["attempted_at"],
        attempt_date=row["attempt_date"],
        attempt_hour=row["attempt_hour"],
        trigger=row["trigger"],
        status=row["status"],
        error=row.get("error"),
        created_at=now,
        updated_at=now,
        created_at_unix=unix,
        updated_at_unix=unix,
    )


def _observation_values(row: dict) -> dict:
    now = get_utc_iso8601_timestamp()
    unix = get_unix_timestamp()
    return dict(
        attempt_id=row["attempt_id"],
        user_id=row["user_id"],
        attempt_date=row["attempt_date"],
        backend=row.get("backend") or "",
        provider=row.get("provider") or "",
        source=row.get("source") or "",
        account_key=row.get("account_key") or "",
        account_name=row.get("account_name"),
        state=row["state"],
        error=row.get("error"),
        observed_at=row.get("observed_at"),
        window_key=row.get("window_key") or "",
        used_percent=row.get("used_percent"),
        reset_at=row.get("reset_at"),
        plan=row.get("plan"),
        limit_reached=row.get("limit_reached"),
        extra=row.get("extra"),
        created_at=now,
        updated_at=now,
        created_at_unix=unix,
        updated_at_unix=unix,
    )


def insert_attempt(attempt: dict, observations: list[dict]) -> bool:
    """Insert one attempt and its observations in a single transaction.

    Returns True when this call wrote the attempt, False when attempt_id
    was already stored (the observations are then skipped too).
    """
    with get_db() as session:
        stmt = (
            insert(ModelUsageLimitAttemptEntity)
            .values(**_attempt_values(attempt))
            .on_conflict_do_nothing(constraint="uq_model_usage_limit_attempt_id")
            .returning(ModelUsageLimitAttemptEntity.attempt_id)
        )
        # rowcount is not the signal. psycopg reports -1 for an
        # INSERT ... ON CONFLICT DO NOTHING, so a conflict looks like a write
        # and the observation insert would attach this attempt's rows to
        # whoever already owns the id. RETURNING is empty exactly on conflict.
        inserted = session.execute(stmt).scalar_one_or_none()
        if inserted is None:
            return False
        if observations:
            obs_stmt = (
                insert(ModelUsageLimitObservationEntity)
                .values([_observation_values(row) for row in observations])
                .on_conflict_do_nothing(constraint="uq_model_usage_limit_observation")
            )
            session.execute(obs_stmt)
        session.flush()
        return True


def count_observations(user_id: int, from_date: date, to_date: date) -> int:
    with get_db() as session:
        return (
            session.query(ModelUsageLimitObservationEntity)
            .filter(ModelUsageLimitObservationEntity.user_id == user_id)
            .filter(ModelUsageLimitObservationEntity.attempt_date >= from_date)
            .filter(ModelUsageLimitObservationEntity.attempt_date <= to_date)
            .count()
        )


def count_attempts(user_id: int, from_date: date, to_date: date) -> int:
    with get_db() as session:
        return (
            session.query(ModelUsageLimitAttemptEntity)
            .filter(ModelUsageLimitAttemptEntity.user_id == user_id)
            .filter(ModelUsageLimitAttemptEntity.attempt_date >= from_date)
            .filter(ModelUsageLimitAttemptEntity.attempt_date <= to_date)
            .count()
        )


def list_attempts(user_id: int, from_date: date, to_date: date) -> list[ModelUsageLimitAttemptEntity]:
    with get_db() as session:
        rows = (
            session.query(ModelUsageLimitAttemptEntity)
            .filter(ModelUsageLimitAttemptEntity.user_id == user_id)
            .filter(ModelUsageLimitAttemptEntity.attempt_date >= from_date)
            .filter(ModelUsageLimitAttemptEntity.attempt_date <= to_date)
            .order_by(
                ModelUsageLimitAttemptEntity.attempted_at.asc(),
                ModelUsageLimitAttemptEntity.attempt_id.asc(),
            )
            .all()
        )
        session.expunge_all()
        return rows


def list_observations(user_id: int, from_date: date, to_date: date) -> list[ModelUsageLimitObservationEntity]:
    with get_db() as session:
        rows = (
            session.query(ModelUsageLimitObservationEntity)
            .filter(ModelUsageLimitObservationEntity.user_id == user_id)
            .filter(ModelUsageLimitObservationEntity.attempt_date >= from_date)
            .filter(ModelUsageLimitObservationEntity.attempt_date <= to_date)
            .order_by(
                ModelUsageLimitObservationEntity.attempt_id.asc(),
                ModelUsageLimitObservationEntity.backend.asc(),
                ModelUsageLimitObservationEntity.window_key.asc(),
            )
            .all()
        )
        session.expunge_all()
        return rows
