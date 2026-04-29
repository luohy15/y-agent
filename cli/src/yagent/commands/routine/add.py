import click
from yagent.api_client import api_request


@click.command('add')
@click.argument('name')
@click.option('--schedule', required=True, help='Cron expression (evaluated in Y_AGENT_TIMEZONE)')
@click.option('--message', required=True, help='Message body to dispatch when fired')
@click.option('--topic', 'target_topic', default=None, help='Target topic (skill name)')
@click.option('--skill', 'target_skill', default=None, help='Target skill (anonymous dispatch)')
@click.option('--work-dir', default=None, help='Working directory for the dispatched chat')
@click.option('--backend', default=None, type=click.Choice(['claude_code', 'codex']), help='Agent backend')
@click.option('--desc', 'description', default=None, help='Description')
@click.option('--disabled', is_flag=True, default=False, help='Create in disabled state')
def routine_add(name, schedule, message, target_topic, target_skill, work_dir, backend, description, disabled):
    """Add a new routine."""
    body = {
        "name": name,
        "schedule": schedule,
        "message": message,
        "enabled": not disabled,
    }
    if description is not None:
        body["description"] = description
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
