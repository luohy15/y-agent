import click
from storage.service import calendar_event as cal_service
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('update')
@click.argument('event_id')
@click.option('--summary', '-s', default=None, help='New summary')
@click.option('--start', default=None, help='New start time (local)')
@click.option('--end', default=None, help='New end time (local)')
@click.option('--desc', default=None, help='New description')
@click.option('--todo-id', default=None, type=int, help='Link to todo ID')
def calendar_update(event_id, summary, start, end, desc, todo_id):
    """Update a calendar event."""
    user_id = get_cli_user_id()
    fields = {}
    if summary is not None:
        fields['summary'] = summary
    if start is not None:
        fields['start_time'] = start
    if end is not None:
        fields['end_time'] = end
    if desc is not None:
        fields['description'] = desc
    if todo_id is not None:
        fields['todo_id'] = todo_id

    if not fields:
        click.echo("No fields to update")
        return

    event = cal_service.update_event(user_id, event_id, **fields)
    if not event:
        click.echo(f"Event '{event_id}' not found")
        return
    click.echo(f"Updated event '{event.summary}' ({event.event_id})")
    update_dashboard(user_id)
