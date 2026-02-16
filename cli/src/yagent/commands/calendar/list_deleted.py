import click
from tabulate import tabulate
from storage.service import calendar_event as cal_service
from storage.service.calendar_event import _utc_to_local
from storage.service.user import get_cli_user_id


@click.command('list-deleted')
@click.option('--limit', '-n', default=50, help='Max results')
def calendar_list_deleted(limit):
    """List soft-deleted calendar events."""
    user_id = get_cli_user_id()
    events = cal_service.list_deleted_events(user_id, limit=limit)
    if not events:
        click.echo("No deleted events found")
        return

    table = []
    for e in events:
        local_start = _utc_to_local(e.start_time)
        table.append([
            e.event_id,
            e.summary,
            local_start,
            e.deleted_at,
        ])
    click.echo(tabulate(table, headers=["ID", "Summary", "Start", "Deleted At"], tablefmt="simple"))
