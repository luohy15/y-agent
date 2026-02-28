import click
from yagent.api_client import api_request


@click.command('activate')
@click.argument('todo_id')
def todo_activate(todo_id):
    """Set a todo to active status."""
    resp = api_request("POST", "/api/todo/activate", json={"todo_id": todo_id})
    todo = resp.json()
    click.echo(f"Activated todo '{todo['name']}' ({todo['todo_id']})")
