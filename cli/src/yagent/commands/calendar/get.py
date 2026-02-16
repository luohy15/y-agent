import click
from storage.service import calendar_event as cal_service
from storage.service.calendar_event import _utc_to_local
from storage.service.user import get_cli_user_id


@click.command('get')
@click.argument('event_id')
def calendar_get(event_id):
    """Show calendar event details."""
    user_id = get_cli_user_id()
    event = cal_service.get_event(user_id, event_id)
    if not event:
        click.echo(f"Event '{event_id}' not found")
        return

    click.echo(f"ID:          {event.event_id}")
    click.echo(f"Summary:     {event.summary}")
    click.echo(f"Start:       {_utc_to_local(event.start_time)}")
    click.echo(f"End:         {_utc_to_local(event.end_time) if event.end_time else '-'}")
    click.echo(f"All Day:     {'Yes' if event.all_day else 'No'}")
    click.echo(f"Status:      {event.status}")
    if event.description:
        click.echo(f"Description: {event.description}")
    if event.source:
        click.echo(f"Source:      {event.source}")
    if event.todo_id:
        click.echo(f"Todo ID:     {event.todo_id}")
    if event.created_at:
        click.echo(f"Created:     {event.created_at}")
