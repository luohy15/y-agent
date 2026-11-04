from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.entity.chat_wakeup import ChatWakeupEntity
from storage.entity.remote_job import ExecutionTargetEntity, RemoteJobEntity
from storage.remote_job import TERMINAL, redact
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


def view(row, *, runner=False):
    excluded = {'id', 'user_id', 'claim_token', 'target_snapshot'}
    data = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in excluded}
    if runner:
        data['claim_token'] = row.claim_token
        data['target_snapshot'] = row.target_snapshot
        return data
    return redact(data)


def targets(user_id):
    with get_db() as session:
        return [view(r) for r in session.query(ExecutionTargetEntity).filter_by(user_id=user_id).all()]


def target(user_id, target_id):
    with get_db() as session:
        row = session.query(ExecutionTargetEntity).filter_by(user_id=user_id, target_id=target_id).first()
        return view(row) if row else None


def upsert_target(user_id, values):
    with get_db() as session:
        stmt = insert(ExecutionTargetEntity).values(user_id=user_id, **values)
        session.execute(stmt.on_conflict_do_update(
            constraint='uq_execution_target_owner', set_={**values, 'updated_at_unix': get_unix_timestamp()}))
    return target(user_id, values['target_id'])


def create(user_id, values):
    with get_db() as session:
        row = RemoteJobEntity(user_id=user_id, job_id=str(uuid4()), **values)
        session.add(row)
        session.flush()
        return view(row)


def get(user_id, job_id):
    with get_db() as session:
        row = session.query(RemoteJobEntity).filter_by(user_id=user_id, job_id=job_id).first()
        return view(row) if row else None


def list_jobs(user_id, limit=50):
    with get_db() as session:
        rows = (session.query(RemoteJobEntity).filter_by(user_id=user_id)
                .order_by(RemoteJobEntity.created_at_unix.desc()).limit(limit).all())
        return [view(r) for r in rows]


@contextmanager
def locked(user_id, job_id):
    with get_db() as session:
        row = (session.query(RemoteJobEntity).filter_by(user_id=user_id, job_id=job_id)
               .populate_existing().with_for_update().first())
        if row is None:
            raise LookupError('JobNotFound')
        yield session, row


def terminal(session, row, state, **fields):
    if row.state in TERMINAL:
        return
    row.state = state
    row.finished_at = get_utc_iso8601_timestamp()
    for key, value in fields.items():
        setattr(row, key, redact(value))
    if row.callback_chat_id:
        session.add(ChatWakeupEntity(
            user_id=row.user_id, wakeup_id=f'remote-job-{row.job_id}',
            chat_id=row.callback_chat_id, trace_id=row.trace_id,
            message=f'Remote job {row.job_id} finished: {state}; read its result with y remote-job result {row.job_id}.',
            due_at_unix=get_unix_timestamp(), status='pending',
        ))


def claim(user_id, job_id):
    with locked(user_id, job_id) as (session, row):
        if row.state != 'queued':
            return None
        if row.cancel_requested:
            terminal(session, row, 'cancelled')
            return None
        row.state = 'dispatched'
        row.attempt += 1
        row.claim_token = str(uuid4())
        row.started_at = get_utc_iso8601_timestamp()
        row.heartbeat_at_unix = get_unix_timestamp()
        return view(row, runner=True)


def fenced(row, attempt, claim_token):
    if row.attempt != attempt or not claim_token or row.claim_token != claim_token:
        raise ValueError('StaleAttempt')


def heartbeat(user_id, job_id, attempt, claim_token, state):
    with locked(user_id, job_id) as (_, row):
        fenced(row, attempt, claim_token)
        if row.state not in TERMINAL:
            if state == 'running':
                row.state = state
            row.heartbeat_at_unix = get_unix_timestamp()
        return view(row)


def finish(user_id, job_id, attempt, claim_token, state, fields):
    with locked(user_id, job_id) as (session, row):
        fenced(row, attempt, claim_token)
        terminal(session, row, state, **fields)
        return view(row)


def cancel(user_id, job_id):
    with locked(user_id, job_id) as (session, row):
        if row.state not in TERMINAL:
            row.cancel_requested = True
            if row.state == 'queued':
                terminal(session, row, 'cancelled')
        return view(row)


def reap(user_id):
    cutoff = get_unix_timestamp() - 15 * 60 * 1000
    with get_db() as session:
        rows = (session.query(RemoteJobEntity).filter_by(user_id=user_id)
                .filter(RemoteJobEntity.state.in_(['dispatched', 'running']),
                        RemoteJobEntity.heartbeat_at_unix < cutoff)
                .with_for_update(skip_locked=True).all())
        for row in rows:
            terminal(session, row, 'host_offline', error_code='RecoveryRequired',
                     error='Heartbeat expired; remote termination is unconfirmed. Do not resubmit until checked.')
        return [view(r) for r in rows]
