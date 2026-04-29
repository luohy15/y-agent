import click

from yagent.api_client import api_request


@click.command('run')
@click.argument('routine_id')
def routine_run(routine_id):
    """Manually fire a routine immediately (debug)."""
    resp = api_request("POST", "/api/routine/run", json={"routine_id": routine_id})
    data = resp.json()
    chat_id = data.get("chat_id")
    if chat_id:
        click.echo(f"Fired routine {routine_id}; chat_id={chat_id}")
    else:
        click.echo(f"Fired routine {routine_id}")
