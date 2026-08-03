import shlex

import click

from yagent.api_client import api_request


@click.command('update')
@click.argument('routine_id')
@click.option('--name', default=None, help='New name')
@click.option('--schedule', default=None, help='New cron expression')
@click.option('--action', default=None, type=click.Choice(['chat', 'vm-command']), help='New routine action')
@click.option('--message', default=None, help='New message body')
@click.option('--command', default=None, help='New shell command to run on the VM, shlex-split to argv (--action vm-command)')
@click.option('--vm-name', default=None, help='New VM to run --command on (--action vm-command only)')
@click.option('--topic', 'target_topic', default=None, help='New target topic')
@click.option('--skill', 'target_skill', default=None, help='New target skill')
@click.option('--work-dir', default=None, help='New work_dir')
@click.option('--backend', default=None, type=click.Choice(['claude_code']), help='New agent backend')
@click.option('--desc', 'description', default=None, help='New description')
@click.option('--guard', default=None, help="Pre-fire guard (module:func dotted path); pass '' to detach")
def routine_update(routine_id, name, schedule, action, message, command, vm_name, target_topic, target_skill, work_dir, backend, description, guard):
    """Update a routine."""
    body = {"routine_id": routine_id}
    if name is not None:
        body["name"] = name
    if schedule is not None:
        body["schedule"] = schedule
    if action is not None:
        body["action"] = action.replace('-', '_')
    if message is not None:
        body["message"] = message
    if command is not None:
        body["command"] = shlex.split(command)
    if vm_name is not None:
        body["vm_name"] = vm_name
    if target_topic is not None:
        body["target_topic"] = target_topic
    if target_skill is not None:
        body["target_skill"] = target_skill
    if work_dir is not None:
        body["work_dir"] = work_dir
    if backend is not None:
        body["backend"] = backend
    if description is not None:
        body["description"] = description
    if guard is not None:
        body["guard"] = guard

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/routine/update", json=body)
    r = resp.json()
    click.echo(f"Updated routine '{r['name']}' ({r['routine_id']})")
