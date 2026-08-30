import click
from yagent.api_client import api_request
from yagent.time_util import utc_to_tz


@click.command('get')
@click.argument('event_id')
def calendar_get(event_id):
    """Show calendar event details."""
    resp = api_request("GET", "/api/calendar/detail", params={"event_id": event_id})
    event = resp.json()

    click.echo(f"ID:          {event['event_id']}")
    click.echo(f"Summary:     {event['summary']}")
    tz_name = event.get("timezone") or "UTC"
    click.echo(f"Start:       {utc_to_tz(event['start_time'], tz_name)}")
    click.echo(f"End:         {utc_to_tz(event['end_time'], tz_name) if event.get('end_time') else '-'}")
    click.echo(f"Timezone:    {tz_name}")
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
