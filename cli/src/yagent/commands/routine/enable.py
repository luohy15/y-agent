import click

from yagent.api_client import api_request


@click.command('enable')
@click.argument('routine_id')
def routine_enable(routine_id):
    """Enable a routine."""
    resp = api_request("POST", "/api/routine/enable", json={"routine_id": routine_id})
    r = resp.json()
    click.echo(f"Enabled routine '{r['name']}' ({r['routine_id']})")
