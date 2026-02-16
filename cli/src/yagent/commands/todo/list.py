import click
from tabulate import tabulate
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('list')
@click.option('--status', '-s', default=None, help='Filter by status')
@click.option('--priority', '-p', default=None, help='Filter by priority')
@click.option('--limit', '-l', default=50, help='Max results')
def todo_list(status, priority, limit):
    """List todos."""
    user_id = get_cli_user_id()
    todos = todo_service.list_todos(user_id, status=status, priority=priority, limit=limit)
    if not todos:
        click.echo("No todos found")
        return

    table = []
    for t in todos:
        table.append([
            t.todo_id,
            t.name,
            t.status,
            t.priority or "-",
            t.due_date or "-",
            ",".join(t.tags) if t.tags else "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Name", "Status", "Priority", "Due", "Tags"], tablefmt="simple"))
