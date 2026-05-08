import click
from tabulate import tabulate
from yagent.api_client import api_request


@click.command('list')
@click.option('--status', '-s', default=None, help='Filter by status')
@click.option('--priority', '-p', default=None, help='Filter by priority')
@click.option('--completed-on', default=None, help='Filter completed_at to a single local-tz date (YYYY-MM-DD)')
@click.option('--completed-since', default=None, help='Lower bound on completed_at, local-tz date (YYYY-MM-DD, inclusive)')
@click.option('--completed-until', default=None, help='Upper bound on completed_at, local-tz date (YYYY-MM-DD, inclusive)')
@click.option('--limit', '-l', default=50, help='Max results')
def todo_list(status, priority, completed_on, completed_since, completed_until, limit):
    """List todos."""
    params = {"limit": limit}
    if status is not None:
        params["status"] = status
    if priority is not None:
        params["priority"] = priority
    if completed_on is not None:
        params["completed_on"] = completed_on
    if completed_since is not None:
        params["completed_since"] = completed_since
    if completed_until is not None:
        params["completed_until"] = completed_until

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
