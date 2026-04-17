import click
from yagent.api_client import api_request


@click.command('cancel')
@click.argument('reminder_id')
def reminder_cancel(reminder_id):
    """Cancel a pending reminder."""
    resp = api_request("DELETE", f"/api/reminder/{reminder_id}")
    r = resp.json()
    click.echo(f"Cancelled reminder '{r['title']}' ({r['reminder_id']})")
