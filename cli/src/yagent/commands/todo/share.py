import click
from tabulate import tabulate
from yagent.api_client import api_request


def _selection(notes, chats, links, clear_items):
    if clear_items and (notes or chats or links):
        raise click.UsageError("--clear-items cannot be combined with --note, --chat or --link")
    body = {}
    if clear_items:
        body["clear_items"] = True
    elif notes or chats or links:
        body["notes"] = list(notes)
        body["chats"] = list(chats)
        body["links"] = list(links)
    return body


@click.command("share")
@click.argument("todo_id")
@click.option("--to", required=True, help="Recipient email or public user id")
@click.option("--note", "notes", multiple=True, help="Related note id, or all")
@click.option("--chat", "chats", multiple=True, help="Related chat id, or all")
@click.option("--link", "links", multiple=True, help="Related link activity id, or all")
@click.option("--clear-items", is_flag=True, help="Replace the selection with nothing")
def todo_share(todo_id, to, notes, chats, links, clear_items):
    """Share one todo with one admitted user."""
    body = {"todo_id": todo_id, "to": to}
    body.update(_selection(notes, chats, links, clear_items))
    result = api_request("POST", "/api/todo/share", json=body).json()
    notice = "notified" if result.get("notified") else "notice failed"
    count = len(result.get("items") or [])
    click.echo(f"Shared {todo_id} with {to}: {result['share_id']} ({notice}, items={count})")


@click.command("unshare")
@click.argument("todo_id")
@click.option("--to", required=True, help="Recipient email or public user id")
def todo_unshare(todo_id, to):
    """Revoke a private todo share."""
    api_request("DELETE", "/api/todo/share", params={"todo_id": todo_id, "to": to})
    click.echo(f"Unshared {todo_id} from {to}")


def _item_count(row):
    return len(row.get("items") or [])


@click.command("shares")
def todo_shares():
    """List todos shared with other users."""
    rows = api_request("GET", "/api/todo/shares").json()
    if not rows:
        click.echo("No outgoing shares")
        return
    table = [[
        row.get("todo_id") or "-",
        row.get("name") or "-",
        row.get("recipient") or "-",
        row.get("shared_at") or "-",
        _item_count(row),
    ] for row in rows]
    click.echo(tabulate(table, headers=["Todo", "Name", "Recipient", "Shared", "Items"], tablefmt="simple"))


@click.command("shared")
def todo_shared():
    """List todos other users have shared with you."""
    rows = api_request("GET", "/api/todo/shared").json()
    if not rows:
        click.echo("No shared todos")
        return
    table = [[
        row.get("share_id") or "-",
        row.get("name") or "-",
        row.get("owner") or "-",
        row.get("status") or "-",
        row.get("shared_at") or "-",
    ] for row in rows]
    click.echo(tabulate(table, headers=["Share", "Name", "Owner", "Status", "Shared"], tablefmt="simple"))


@click.command("public")
def todo_public():
    """List public todo shares you have visited."""
    rows = api_request("GET", "/api/todo/public").json()
    if not rows:
        click.echo("No visited public todos")
        return
    table = [[
        row.get("share_id") or "-",
        row.get("name") or "-",
        row.get("status") or "-",
        row.get("last_visited_at") or "-",
    ] for row in rows]
    click.echo(tabulate(table, headers=["Share", "Name", "Status", "Visited"], tablefmt="simple"))
