import click
from yagent.api_client import api_request


@click.command('finish')
@click.argument('todo_id')
def todo_finish(todo_id):
    """Mark a todo as completed."""
    resp = api_request("POST", "/api/todo/finish", json={"todo_id": todo_id})
    todo = resp.json()
    click.echo(f"Completed todo '{todo['name']}' ({todo['todo_id']})")
