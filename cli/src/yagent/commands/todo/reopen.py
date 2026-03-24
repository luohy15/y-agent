import click
from yagent.api_client import api_request


@click.command('reopen')
@click.argument('todo_id')
def todo_reopen(todo_id):
    """Reopen a completed todo (set to active)."""
    resp = api_request("POST", "/api/todo/status", json={"todo_id": todo_id, "status": "active"})
    todo = resp.json()
    click.echo(f"Reopened todo '{todo['name']}' ({todo['todo_id']})")
