import click
from yagent.api_client import api_request


@click.command("resume")
@click.argument("todo_id")
def todo_resume(todo_id):
    """Move an awaiting todo to active. Active is an idempotent no-op."""
    resp = api_request("POST", "/api/todo/resume", json={"todo_id": todo_id})
    todo = resp.json()
    if todo.get("changed"):
        click.echo(f"Resumed todo '{todo['name']}' ({todo['todo_id']})")
    else:
        click.echo(f"Todo '{todo['name']}' ({todo['todo_id']}) already {todo['status']}")
