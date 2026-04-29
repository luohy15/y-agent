import click

from yagent.api_client import api_request


@click.command('delete')
@click.argument('routine_id')
def routine_delete(routine_id):
    """Delete a routine."""
    api_request("POST", "/api/routine/delete", json={"routine_id": routine_id})
    click.echo(f"Deleted routine {routine_id}")
