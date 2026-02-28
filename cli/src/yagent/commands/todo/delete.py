import click
from yagent.api_client import api_request


@click.command('delete')
@click.argument('todo_id')
def todo_delete(todo_id):
    """Soft delete a todo."""
    resp = api_request("POST", "/api/todo/delete", json={"todo_id": todo_id})
    todo = resp.json()
    click.echo(f"Deleted todo '{todo['name']}' ({todo['todo_id']})")
