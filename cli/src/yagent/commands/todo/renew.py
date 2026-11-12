import click
from yagent.api_client import api_request
from .sla_text import sla_label


@click.command('renew')
@click.argument('todo_id')
@click.option('--sla', default=None, help='Completion promise: Nd, Nw or YYYY-MM-DD (at most 14 days)')
def todo_renew(todo_id, sla):
    """Renew an open non-pinned todo from today."""
    body = {"todo_id": todo_id}
    if sla is not None:
        body["sla"] = sla
    todo = api_request("POST", "/api/todo/renew", json=body).json()
    click.echo(f"Renewed todo {todo['todo_id']}: {sla_label(todo)}")
