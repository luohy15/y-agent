import click
from tabulate import tabulate
from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command('list-deleted')
@click.option('--limit', '-n', default=50, help='Max results')
def calendar_list_deleted(limit):
    """List soft-deleted calendar events."""
    resp = api_request("GET", "/api/calendar/deleted", params={"limit": limit})
    events = resp.json()
    if not events:
        click.echo("No deleted events found")
        return

    table = []
    for e in events:
        local_start = utc_to_local(e["start_time"])
        table.append([
            e["event_id"],
            e["summary"],
            local_start,
            e.get("deleted_at", ""),
        ])
    click.echo(tabulate(table, headers=["ID", "Summary", "Start", "Deleted At"], tablefmt="simple"))
