import click
from storage.service import calendar_event as cal_service
from storage.service.user import get_cli_user_id


@click.command('add')
@click.option('--summary', '-s', required=True, help='Event summary')
@click.option('--start', required=True, help='Start time (local, e.g. 2026-02-16T10:00)')
@click.option('--end', default=None, help='End time (local)')
@click.option('--desc', default=None, help='Description')
@click.option('--todo-id', default=None, type=int, help='Link to todo ID')
@click.option('--all-day', is_flag=True, default=False, help='All-day event')
@click.option('--source', default=None, help='Event source')
def calendar_add(summary, start, end, desc, todo_id, all_day, source):
    """Add a new calendar event."""
    user_id = get_cli_user_id()
    event = cal_service.add_event(
        user_id, summary, start,
        end_time=end, description=desc,
        todo_id=todo_id, all_day=all_day, source=source,
    )
    click.echo(f"Created event '{event.summary}' ({event.event_id})")
