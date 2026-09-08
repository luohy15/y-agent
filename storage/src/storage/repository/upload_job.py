"""Owner-scoped upload jobs and conditional state transitions."""

from sqlalchemy import and_, or_, select, update
from storage.database.base import get_db
from storage.entity.upload_job import UploadJobEntity as Job
from storage.entity.user import UserEntity
from storage.util import get_utc_iso8601_timestamp


def _dict(row):
    return {column.name: getattr(row, column.name) for column in Job.__table__.columns}


def owner_id(public_user_id):
    with get_db() as session:
        return session.scalar(select(UserEntity.id).where(
            UserEntity.user_id == public_user_id, UserEntity.deleted.is_(False)))


def create(user_id, **fields):
    with get_db() as session:
        row = Job(user_id=user_id, **fields)
        session.add(row)
        session.flush()
        return _dict(row)


def get(user_id, upload_id):
    with get_db() as session:
        row = session.scalar(select(Job).where(Job.user_id == user_id, Job.upload_id == upload_id))
        return _dict(row) if row else None


def batch(user_id, batch_id):
    with get_db() as session:
        return [_dict(row) for row in session.scalars(select(Job).where(
            Job.user_id == user_id, Job.batch_id == batch_id).order_by(Job.id))]


def active(user_id):
    # Include the whole batch while any job is in flight, plus recently finished
    # batches so expired authorizations remain discoverable after a reload.
    from storage.util import get_unix_timestamp
    with get_db() as session:
        batches = select(Job.batch_id).where(Job.user_id == user_id, or_(
            Job.status.in_(["authorized", "staged", "transferring"]),
            Job.updated_at_unix >= get_unix_timestamp() - 86400))
        return [_dict(row) for row in session.scalars(select(Job).where(
            Job.user_id == user_id, Job.batch_id.in_(batches)).order_by(Job.id))]


def _update(user_id, upload_id, guards, **fields):
    with get_db() as session:
        row = session.scalars(update(Job).where(
            Job.user_id == user_id, Job.upload_id == upload_id, *guards
        ).values(**fields).returning(Job)).first()
        return _dict(row) if row else None


def promote(user_id, upload_id, version, now):
    return _update(user_id, upload_id, [Job.status == "authorized", Job.staging_version_id.is_(None)],
                   staging_version_id=version, status="staged", staged_at=get_utc_iso8601_timestamp(),
                   last_enqueued_at_unix=now, error=None)


def claim(user_id, upload_id, token, now):
    return _update(user_id, upload_id, [or_(Job.status == "staged", and_(
        Job.status == "transferring", Job.lease_expires_at_unix < now))],
        status="transferring", lease_token=token, lease_expires_at_unix=now + 900,
        attempts=Job.attempts + 1)


def finish_attempt(user_id, upload_id, token, status, error=None, now=None):
    fields = dict(status=status, error=error)
    if status == "saved":
        fields["saved_at"] = get_utc_iso8601_timestamp()
    if status == "staged":
        fields.update(lease_token=None, lease_expires_at_unix=None, last_enqueued_at_unix=now)
    return _update(user_id, upload_id, [Job.status == "transferring", Job.lease_token == token], **fields)


def retry(user_id, upload_id, now):
    return _update(user_id, upload_id, [Job.status == "failed"], status="staged", error=None,
                   lease_token=None, lease_expires_at_unix=None, attempts=0, last_enqueued_at_unix=now)


def recovery_candidates(now):
    with get_db() as session:
        return [_dict(row) for row in session.scalars(select(Job).where(or_(
            and_(Job.status == "authorized", Job.created_at_unix < now - 2400),
            and_(Job.status == "staged", or_(Job.last_enqueued_at_unix < now - 900, Job.attempts >= 5)),
            and_(Job.status == "transferring", Job.lease_expires_at_unix < now),
        )).order_by(Job.id))]


def recover(row, now, error=None):
    if row["status"] == "authorized":
        guards = [Job.status == "authorized", Job.staging_version_id.is_(None), Job.created_at_unix < now - 2400]
    elif row["status"] == "staged":
        guards = [Job.status == "staged"]
        if not error:
            guards.append(Job.last_enqueued_at_unix < now - 900)
    else:
        guards = [Job.status == "transferring", Job.lease_token == row["lease_token"],
                  Job.lease_expires_at_unix < now]
    if error:
        fields = dict(status="failed", error=error)
    else:
        fields = dict(status="staged", lease_token=None, lease_expires_at_unix=None,
                      last_enqueued_at_unix=now)
    return _update(row["user_id"], row["upload_id"], guards, **fields)
