import click
from yagent.api_client import api_request


@click.command('update')
@click.argument('todo_id')
@click.option('--name', '-n', default=None, help='New name')
@click.option('--desc', '-d', default=None, help='New description')
@click.option('--due', '-u', default=None, help='New due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='New priority')
@click.option('--tags', '-t', default=None, help='New comma-separated tags')
@click.option('--progress', default=None, help='Progress note')
def todo_update(todo_id, name, desc, due, priority, tags, progress):
    """Update a todo."""
    body = {"todo_id": todo_id}
    if name is not None:
        body["name"] = name
    if desc is not None:
        body["desc"] = desc
    if due is not None:
        body["due_date"] = due
    if priority is not None:
        body["priority"] = priority
    if tags is not None:
        body["tags"] = [t.strip() for t in tags.split(',')]
    if progress is not None:
        body["progress"] = progress

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/todo/update", json=body)
    todo = resp.json()
    click.echo(f"Updated todo '{todo['name']}' ({todo['todo_id']})")
