import click
from tabulate import tabulate
from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options
from yagent.time_util import utc_to_local


@click.command('list')
@time_filter_options
@click.option('--limit', '-n', default=50, help='Max results')
@click.option('--source', default=None, help='Filter by source')
@click.option('--todo-id', default=None, type=int, help='Filter by linked todo')
@click.option('--include-deleted', is_flag=True, default=False, help='Include deleted events')
@click.option('--tag', default=None, help='Filter events by entity_tag (exact tag match)')
def calendar_list(on, from_, to, created_on, created_from, created_to,
                  updated_on, updated_from, updated_to,
                  limit, source, todo_id, include_deleted, tag):
    """List calendar events. Canonical time field: start_time."""
    params = {"limit": limit}
    if source is not None:
        params["source"] = source
    if todo_id is not None:
        params["todo_id"] = todo_id
    if include_deleted:
        params["include_deleted"] = True
    if tag:
        params["tag"] = tag
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))

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
