import json
import os

import click

from storage.remote_job import FEED_URL
from yagent.api_client import api_request


def output(method, suffix='', **kwargs):
    value = api_request(method, '/api/remote-jobs' + suffix, **kwargs).json()
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


@click.group('remote-job')
def remote_job_group():
    """Bounded Mac Codex browser jobs (not general remote execution)."""


@remote_job_group.group('target')
def target_group():
    """Configure the owner's existing mac SSH alias."""


@target_group.command('add')
@click.argument('target_id', type=click.Choice(['mac']))
def target_add(target_id):
    output('POST', '/targets', json={'target_id': target_id})


@target_group.command('list')
def target_list():
    output('GET', '/targets')


@remote_job_group.command('submit')
@click.option('--target', default='mac')
@click.option('--executor', default='codex')
@click.option('--operation', default='browser_open')
@click.option('--url')
@click.option('--fresh-post', is_flag=True)
@click.option('--timeout', 'timeout_seconds', default=180, type=click.IntRange(1, 600))
@click.option('--todo', 'todo_id')
@click.option('--trace-id', envvar='Y_TRACE_ID')
@click.option('--callback-chat-id', envvar='Y_CHAT_ID')
def submit(target, executor, operation, url, fresh_post, timeout_seconds, todo_id, trace_id, callback_chat_id):
    if bool(url) == bool(fresh_post):
        raise click.UsageError('Choose exactly one of --url or --fresh-post')
    output('POST', json=dict(target=target, executor=executor, operation=operation,
                            payload={'url': url} if url else {'feed_url': FEED_URL},
                            timeout_seconds=timeout_seconds, todo_id=todo_id,
                            trace_id=trace_id, callback_chat_id=callback_chat_id if trace_id else None))


@remote_job_group.command('list')
@click.option('--limit', default=50, type=click.IntRange(1, 100))
def list_jobs(limit):
    output('GET', params={'limit': limit})


@remote_job_group.command('get')
@click.argument('job_id')
def get(job_id):
    output('GET', '/' + job_id)


@remote_job_group.command('result')
@click.argument('job_id')
@click.option('--json', 'as_json', is_flag=True, help='Output JSON (also the default).')
def result(job_id, as_json):
    output('GET', '/' + job_id + '/result')


@remote_job_group.command('cancel')
@click.argument('job_id')
def cancel(job_id):
    output('POST', '/' + job_id + '/cancel')


@remote_job_group.command('run')
@click.argument('job_id')
def run(job_id):
    """Internal EC2 runner. Atomic API claim prevents duplicate execution."""
    from yagent.remote_job_runner import run as run_job
    # Do not inherit the spawning chat's identity into the remote operation.
    for key in ('Y_CHAT_ID', 'Y_TRACE_ID', 'Y_ROLE'):
        os.environ.pop(key, None)
    run_job(job_id)


@remote_job_group.command('reap')
def reap():
    """Mark stale running jobs host_offline, without claiming remote termination."""
    output('POST', '/reap')
