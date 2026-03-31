import click
from yagent.api_client import api_request


@click.command('assoc')
@click.argument('link_id')
@click.option('--todo', '-t', required=True, help='Todo ID to associate with')
def link_assoc(link_id, todo):
    """Associate a link with a todo."""
    resp = api_request("POST", "/api/link-todo", json={"link_id": link_id, "todo_id": todo})
    data = resp.json()
    if data.get("created"):
        click.echo(f"Associated link {link_id} with todo {todo}")
    else:
        click.echo(f"Association already exists")


@click.command('unassoc')
@click.argument('link_id')
@click.option('--todo', '-t', required=True, help='Todo ID to disassociate from')
def link_unassoc(link_id, todo):
    """Remove association between a link and a todo."""
    resp = api_request("POST", "/api/link-todo/delete", json={"link_id": link_id, "todo_id": todo})
    data = resp.json()
    if data.get("deleted"):
        click.echo(f"Removed association between link {link_id} and todo {todo}")
    else:
        click.echo(f"Association not found")
