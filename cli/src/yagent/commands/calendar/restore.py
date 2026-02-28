import click
from yagent.api_client import api_request


@click.command('restore')
@click.argument('event_id')
def calendar_restore(event_id):
    """Restore a soft-deleted calendar event."""
    resp = api_request("POST", "/api/calendar/restore", json={"event_id": event_id})
    event = resp.json()
    click.echo(f"Restored event '{event['summary']}' ({event['event_id']})")
