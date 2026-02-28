import click
from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command('get')
@click.argument('event_id')
def calendar_get(event_id):
    """Show calendar event details."""
    resp = api_request("GET", "/api/calendar/detail", params={"event_id": event_id})
    event = resp.json()

    click.echo(f"ID:          {event['event_id']}")
    click.echo(f"Summary:     {event['summary']}")
    click.echo(f"Start:       {utc_to_local(event['start_time'])}")
    click.echo(f"End:         {utc_to_local(event['end_time']) if event.get('end_time') else '-'}")
    click.echo(f"All Day:     {'Yes' if event.get('all_day') else 'No'}")
    click.echo(f"Status:      {event.get('status', '')}")
    if event.get("description"):
        click.echo(f"Description: {event['description']}")
    if event.get("source"):
        click.echo(f"Source:      {event['source']}")
    if event.get("todo_id"):
        click.echo(f"Todo ID:     {event['todo_id']}")
    if event.get("created_at"):
        click.echo(f"Created:     {event['created_at']}")
