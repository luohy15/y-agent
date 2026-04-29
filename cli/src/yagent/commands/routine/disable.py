import click

from yagent.api_client import api_request


@click.command('disable')
@click.argument('routine_id')
def routine_disable(routine_id):
    """Disable a routine."""
    resp = api_request("POST", "/api/routine/disable", json={"routine_id": routine_id})
    r = resp.json()
    click.echo(f"Disabled routine '{r['name']}' ({r['routine_id']})")
