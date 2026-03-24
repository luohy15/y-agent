import click
from yagent.api_client import api_request


@click.command('status')
@click.argument('todo_id')
@click.argument('status')
def todo_status(todo_id, status):
    """Update a todo's status (pending/active/completed/deleted)."""
    resp = api_request("POST", "/api/todo/status", json={"todo_id": todo_id, "status": status})
    todo = resp.json()
    click.echo(f"Updated todo '{todo['name']}' ({todo['todo_id']}) → {todo['status']}")
