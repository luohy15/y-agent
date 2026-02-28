import click
from yagent.api_client import api_request


@click.command('delete')
@click.argument('event_id')
def calendar_delete(event_id):
    """Soft delete a calendar event."""
    resp = api_request("POST", "/api/calendar/delete", json={"event_id": event_id})
    event = resp.json()
    click.echo(f"Deleted event '{event['summary']}' ({event['event_id']})")
