import click
from yagent.api_client import api_request


@click.command('pin')
@click.argument('todo_id')
def todo_pin(todo_id):
    """Pin a todo to the top of lists."""
    resp = api_request("POST", "/api/todo/pin", json={"todo_id": todo_id, "pinned": True})
    todo = resp.json()
    click.echo(f"Pinned todo '{todo['name']}' ({todo['todo_id']})")


@click.command('unpin')
@click.argument('todo_id')
def todo_unpin(todo_id):
    """Unpin a todo."""
    resp = api_request("POST", "/api/todo/pin", json={"todo_id": todo_id, "pinned": False})
    todo = resp.json()
    click.echo(f"Unpinned todo '{todo['name']}' ({todo['todo_id']})")
