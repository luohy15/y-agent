import click
from yagent.api_client import api_request


@click.command('assoc')
@click.argument('activity_id')
@click.option('--todo', '-t', required=True, help='Todo ID to associate with')
def link_assoc(activity_id, todo):
    """Associate a link activity with a todo."""
    resp = api_request("POST", "/api/link-todo", json={"activity_id": activity_id, "todo_id": todo})
    data = resp.json()
    if data.get("created"):
        click.echo(f"Associated activity {activity_id} with todo {todo}")
    else:
        click.echo(f"Association already exists")


@click.command('unassoc')
@click.argument('activity_id')
@click.option('--todo', '-t', required=True, help='Todo ID to disassociate from')
def link_unassoc(activity_id, todo):
    """Remove association between a link activity and a todo."""
    resp = api_request("POST", "/api/link-todo/delete", json={"activity_id": activity_id, "todo_id": todo})
    data = resp.json()
    if data.get("deleted"):
        click.echo(f"Removed association between activity {activity_id} and todo {todo}")
    else:
        click.echo(f"Association not found")
