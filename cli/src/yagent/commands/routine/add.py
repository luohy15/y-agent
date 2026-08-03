import shlex

import click
from yagent.api_client import api_request


@click.command('add')
@click.argument('name')
@click.option('--schedule', required=True, help='Cron expression (evaluated in Y_AGENT_TIMEZONE)')
@click.option('--action', type=click.Choice(['chat', 'vm-command']), default='chat', help='Routine action (default: chat)')
@click.option('--message', default=None, help="Message body to dispatch when fired (required for --action chat)")
@click.option('--command', default=None, help="Shell command to run on the VM, shlex-split to argv (required for --action vm-command)")
@click.option('--vm-name', default=None, help='VM to run --command on (--action vm-command only); default VM if omitted')
@click.option('--topic', 'target_topic', default=None, help='Target topic (skill name)')
@click.option('--skill', 'target_skill', default=None, help='Target skill (anonymous dispatch)')
@click.option('--work-dir', default=None, help='Working directory for the dispatched chat')
@click.option('--backend', default=None, type=click.Choice(['claude_code']), help='Agent backend')
@click.option('--desc', 'description', default=None, help='Description')
@click.option('--guard', default=None, help='Pre-fire guard (module:func dotted path)')
@click.option('--disabled', is_flag=True, default=False, help='Create in disabled state')
def routine_add(name, schedule, action, message, command, vm_name, target_topic, target_skill, work_dir, backend, description, guard, disabled):
    """Add a new routine."""
    action = action.replace('-', '_')
    if action == 'chat' and not message:
        raise click.UsageError("--message is required for --action chat")
    if action == 'vm_command' and not command:
        raise click.UsageError("--command is required for --action vm-command")

    body = {
        "name": name,
        "schedule": schedule,
        "action": action,
        "enabled": not disabled,
    }
    if message is not None:
        body["message"] = message
    if command is not None:
        body["command"] = shlex.split(command)
    if vm_name is not None:
        body["vm_name"] = vm_name
    if description is not None:
        body["description"] = description
    if guard is not None:
        body["guard"] = guard
    if target_topic is not None:
        body["target_topic"] = target_topic
    if target_skill is not None:
        body["target_skill"] = target_skill
    if work_dir is not None:
        body["work_dir"] = work_dir
    if backend is not None:
        body["backend"] = backend

    resp = api_request("POST", "/api/routine", json=body)
    r = resp.json()
    state = "enabled" if r.get("enabled") else "disabled"
    click.echo(f"Created routine '{r['name']}' ({r['routine_id']}) [{state}] schedule='{r['schedule']}'")
