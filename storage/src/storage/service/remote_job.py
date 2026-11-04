import json
import os

from storage.remote_job import MAX_BYTES, TERMINAL, validate_payload, validate_target
from storage.repository import remote_job as repo


def list_targets(user_id):
    return repo.targets(user_id)


def add_target(user_id, values):
    return repo.upsert_target(user_id, validate_target(values))


def validate_submission(target, executor, operation, payload):
    if not target or not target['enabled']:
        raise LookupError('HostNotConfigured')
    if executor != 'codex' or operation != 'browser_open':
        raise ValueError('OperationNotAllowed')
    if executor not in target['executors'] or operation not in target['operations']:
        raise ValueError('OperationNotAllowed')
    validate_target(target)
    return validate_payload(payload)


async def submit(user_id, *, target, executor, operation, payload, timeout_seconds=180,
                 todo_id=None, trace_id=None, callback_chat_id=None):
    from storage.service import chat as chat_service
    configured = repo.target(user_id, target)
    validate_submission(configured, executor, operation, payload)
    if not 1 <= timeout_seconds <= 600:
        raise ValueError('InvalidTimeout')
    if todo_id and trace_id and todo_id != trace_id:
        raise ValueError('TraceMismatch')
    if callback_chat_id:
        chat = await chat_service.get_chat(user_id, callback_chat_id)
        if not chat or not trace_id or chat.trace_id != trace_id:
            raise ValueError('CallbackTraceMismatch')
        chat_service.validate_dispatch_target(chat)
    elif trace_id:
        raise ValueError('CallbackRequiredForTrace')
    queue_url = os.environ.get('SQS_QUEUE_URL')
    if not queue_url:
        raise ValueError('QueueNotConfigured')
    job = repo.create(user_id, dict(
        target_id=target, executor=executor, operation=operation, payload=payload,
        target_snapshot=configured, timeout_seconds=timeout_seconds, todo_id=todo_id,
        trace_id=trace_id, callback_chat_id=callback_chat_id,
    ))
    try:
        import boto3
        boto3.client('sqs').send_message(QueueUrl=queue_url, MessageBody=json.dumps(
            {'task_type': 'remote_job', 'job_id': job['job_id'], 'user_id': user_id}))
    except Exception:
        with repo.locked(user_id, job['job_id']) as (session, row):
            if row.state == 'queued':
                repo.terminal(session, row, 'failed', error_code='EnqueueFailed')
        return repo.get(user_id, job['job_id'])
    return job


def get(user_id, job_id):
    job = repo.get(user_id, job_id)
    if job is None:
        raise LookupError('JobNotFound')
    return job


def list_jobs(user_id, limit=50):
    return repo.list_jobs(user_id, limit)


def claim(user_id, job_id):
    return repo.claim(user_id, job_id)


def heartbeat(user_id, job_id, attempt, claim_token, state):
    if state not in {'dispatched', 'running'}:
        raise ValueError('InvalidState')
    return repo.heartbeat(user_id, job_id, attempt, claim_token, state)


def finish(user_id, job_id, *, attempt, claim_token, state, termination_confirmed=False, **fields):
    if state not in TERMINAL:
        raise ValueError('InvalidState')
    if state in {'cancelled', 'timeout'} and not termination_confirmed:
        raise ValueError('TerminationUnconfirmed')
    if state == 'completed' and fields.get('exit_code') != 0:
        raise ValueError('ExitNotSuccessful')
    if any(len(json.dumps(v).encode()) > MAX_BYTES for v in fields.values()):
        raise ValueError('ResultTooLarge')
    return repo.finish(user_id, job_id, attempt, claim_token, state, fields)


def cancel(user_id, job_id):
    return repo.cancel(user_id, job_id)


def reap(user_id):
    return repo.reap(user_id)
