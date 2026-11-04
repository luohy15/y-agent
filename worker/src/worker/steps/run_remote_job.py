import shlex

from agent.vm_command import run_vm_command
from storage.remote_job import job_uuid
from storage.service import remote_job as service


def build_launch_command(job_id):
    job_uuid(job_id)
    command = f'exec "$HOME/.local/bin/y" remote-job run {job_id}'
    return ('unset TMUX; /usr/bin/tmux new-session -d -s '
            + shlex.quote(f'yj-{job_id}') + ' ' + shlex.quote(command))


async def handle_remote_job(body):
    user_id, job_id = body['user_id'], body['job_id']
    job = service.get(user_id, job_id)
    if job['state'] != 'queued':
        return
    # The API claim inside the runner is the single-winner execution fence.
    # A duplicate SQS launch may fail tmux creation; retry never reruns a claim.
    await run_vm_command(user_id, ['bash', '-lc', build_launch_command(job_id)],
                         timeout=30, check=True)
