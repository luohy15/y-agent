import click
from yagent.api_client import api_request


@click.command('deactivate')
@click.argument('todo_id')
def todo_deactivate(todo_id):
    """Set a todo back to pending status."""
    resp = api_request("POST", "/api/todo/deactivate", json={"todo_id": todo_id})
    todo = resp.json()
    click.echo(f"Deactivated todo '{todo['name']}' ({todo['todo_id']})")
