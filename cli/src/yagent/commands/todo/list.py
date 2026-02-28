import click
from tabulate import tabulate
from yagent.api_client import api_request


@click.command('list')
@click.option('--status', '-s', default=None, help='Filter by status')
@click.option('--priority', '-p', default=None, help='Filter by priority')
@click.option('--limit', '-l', default=50, help='Max results')
def todo_list(status, priority, limit):
    """List todos."""
    params = {"limit": limit}
    if status is not None:
        params["status"] = status
    if priority is not None:
        params["priority"] = priority

    resp = api_request("GET", "/api/todo/list", params=params)
    todos = resp.json()
    if not todos:
        click.echo("No todos found")
        return

    table = []
    for t in todos:
        table.append([
            t["todo_id"],
            t["name"],
            t["status"],
            t.get("priority") or "-",
            t.get("due_date") or "-",
            ",".join(t["tags"]) if t.get("tags") else "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Name", "Status", "Priority", "Due", "Tags"], tablefmt="simple"))
