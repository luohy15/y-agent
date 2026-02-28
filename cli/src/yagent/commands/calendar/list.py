import click
from tabulate import tabulate
from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command('list')
@click.option('--date', '-d', default=None, help='Filter by date (YYYY-MM-DD)')
@click.option('--start', default=None, help='Filter start >= this time (local, e.g. 2026-02-25T08:00)')
@click.option('--end', default=None, help='Filter start <= this time (local, e.g. 2026-02-25T20:00)')
@click.option('--limit', '-n', default=50, help='Max results')
@click.option('--source', default=None, help='Filter by source')
@click.option('--todo-id', default=None, type=int, help='Filter by linked todo')
@click.option('--include-deleted', is_flag=True, default=False, help='Include deleted events')
def calendar_list(date, start, end, limit, source, todo_id, include_deleted):
    """List calendar events."""
    params = {"limit": limit}
    if date is not None:
        params["date"] = date
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    if source is not None:
        params["source"] = source
    if todo_id is not None:
        params["todo_id"] = todo_id
    if include_deleted:
        params["include_deleted"] = True

    resp = api_request("GET", "/api/calendar/list", params=params)
    events = resp.json()
    if not events:
        click.echo("No events found")
        return

    table = []
    for e in events:
        local_start = utc_to_local(e["start_time"])
        local_end = utc_to_local(e["end_time"]) if e.get("end_time") else "-"
        table.append([
            e["event_id"],
            e["summary"],
            local_start,
            local_end,
            "Yes" if e.get("all_day") else "No",
            e.get("status", ""),
        ])
    click.echo(tabulate(table, headers=["ID", "Summary", "Start", "End", "All Day", "Status"], tablefmt="simple"))
