import click

from yagent.api_client import api_request


@click.command('update')
@click.argument('routine_id')
@click.option('--name', default=None, help='New name')
@click.option('--schedule', default=None, help='New cron expression')
@click.option('--message', default=None, help='New message body')
@click.option('--topic', 'target_topic', default=None, help='New target topic')
@click.option('--skill', 'target_skill', default=None, help='New target skill')
@click.option('--work-dir', default=None, help='New work_dir')
@click.option('--backend', default=None, type=click.Choice(['claude_code', 'codex']), help='New agent backend')
@click.option('--desc', 'description', default=None, help='New description')
def routine_update(routine_id, name, schedule, message, target_topic, target_skill, work_dir, backend, description):
    """Update a routine."""
    body = {"routine_id": routine_id}
    if name is not None:
        body["name"] = name
    if schedule is not None:
        body["schedule"] = schedule
    if message is not None:
        body["message"] = message
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

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/routine/update", json=body)
    r = resp.json()
    click.echo(f"Updated routine '{r['name']}' ({r['routine_id']})")
