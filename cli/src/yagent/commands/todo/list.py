import click
from tabulate import tabulate
from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options


@click.command('list')
@click.option('--status', '-s', default=None, help='Filter by status')
@click.option('--priority', '-p', default=None, help='Filter by priority')
@time_filter_options
@click.option('--limit', '-l', default=50, help='Max results')
def todo_list(status, priority, on, from_, to, created_on, created_from, created_to,
              updated_on, updated_from, updated_to, limit):
    """List todos. Canonical time field: completed_at."""
    params = {"limit": limit}
    if status is not None:
        params["status"] = status
    if priority is not None:
        params["priority"] = priority
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))

    resp = api_request("GET", "/api/todo/list", params=params)
    todos = resp.json()
    if not todos:
        click.echo("No todos found")
        return

    table = []
    for t in todos:
        pin_marker = "[P] " if t.get("pinned") else ""
        table.append([
            t["todo_id"],
            f"{pin_marker}{t['name']}",
            t["status"],
            t.get("priority") or "-",
            t.get("due_date") or "-",
            ",".join(t["tags"]) if t.get("tags") else "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Name", "Status", "Priority", "Due", "Tags"], tablefmt="simple"))
