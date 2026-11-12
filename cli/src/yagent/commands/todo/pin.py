import click
from yagent.api_client import api_request


@click.command('pin')
@click.argument('todo_id')
def todo_pin(todo_id):
    """Make a todo a long-term goal without an SLA."""
    resp = api_request("POST", "/api/todo/pin", json={"todo_id": todo_id, "pinned": True})
    todo = resp.json()
    click.echo(f"Pinned todo '{todo['name']}' ({todo['todo_id']})")


@click.command('unpin')
@click.argument('todo_id')
@click.option('--sla', default=None, help='Fresh completion promise: Nd, Nw or YYYY-MM-DD')
def todo_unpin(todo_id, sla):
    """Unpin a todo."""
    body = {"todo_id": todo_id, "pinned": False}
    if sla is not None:
        body["sla"] = sla
    resp = api_request("POST", "/api/todo/pin", json=body)
    todo = resp.json()
    click.echo(f"Unpinned todo '{todo['name']}' ({todo['todo_id']})")
