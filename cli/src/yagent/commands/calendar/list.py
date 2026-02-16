import click
from tabulate import tabulate
from storage.service import calendar_event as cal_service
from storage.service.calendar_event import _utc_to_local
from storage.service.user import get_cli_user_id


@click.command('list')
@click.option('--date', '-d', default=None, help='Filter by date (YYYY-MM-DD)')
@click.option('--start', default=None, help='Filter start >= this time')
@click.option('--end', default=None, help='Filter start <= this time')
@click.option('--limit', '-n', default=50, help='Max results')
@click.option('--source', default=None, help='Filter by source')
@click.option('--todo-id', default=None, type=int, help='Filter by linked todo')
@click.option('--include-deleted', is_flag=True, default=False, help='Include deleted events')
def calendar_list(date, start, end, limit, source, todo_id, include_deleted):
    """List calendar events."""
    user_id = get_cli_user_id()
    events = cal_service.list_events(
        user_id, date=date, start=start, end=end,
        source=source, todo_id=todo_id,
        include_deleted=include_deleted, limit=limit,
    )
    if not events:
        click.echo("No events found")
        return

    table = []
    for e in events:
        local_start = _utc_to_local(e.start_time)
        local_end = _utc_to_local(e.end_time) if e.end_time else "-"
        table.append([
            e.event_id,
            e.summary,
            local_start,
            local_end,
            "Yes" if e.all_day else "No",
            e.status,
        ])
    click.echo(tabulate(table, headers=["ID", "Summary", "Start", "End", "All Day", "Status"], tablefmt="simple"))
