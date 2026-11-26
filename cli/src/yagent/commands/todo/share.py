import click
import httpx
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


def _print_shared():
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


def _field(todo, key):
    value = todo.get(key)
    if value is None or value == "":
        return "-"
    if key == "tags":
        return ", ".join(value) if value else "-"
    return value


def _echo_block(title, body):
    click.echo(title)
    text = body if isinstance(body, str) else ""
    if text:
        click.echo(text)


def _echo_messages(messages, full):
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role") or "-"
        content = message.get("content") or ""
        if role == "tool":
            if full:
                click.echo("  tool: [tool result removed]")
            continue
        if not content.strip():
            continue
        click.echo(f"  {role}: {content}")


def _render_shared_detail(payload, summary=False, full=False):
    todo = payload.get("todo") if isinstance(payload, dict) else None
    if not isinstance(todo, dict):
        raise click.ClickException("Shared todo detail is missing")
    click.echo(f"Share:     {_field(todo, 'share_id')}")
    click.echo(f"Name:      {_field(todo, 'name')}")
    click.echo(f"Status:    {_field(todo, 'status')}")
    click.echo(f"Priority:  {_field(todo, 'priority')}")
    click.echo(f"Due:       {_field(todo, 'due_date')}")
    click.echo(f"SLA:       {_field(todo, 'sla_due_at')}")
    click.echo(f"Tags:      {_field(todo, 'tags')}")
    click.echo(f"Owner:     {_field(todo, 'owner')}")
    click.echo(f"Shared:    {_field(todo, 'shared_at')}")
    if todo.get("completed_at"):
        click.echo(f"Completed: {todo['completed_at']}")
    if todo.get("desc"):
        click.echo(f"Desc:      {todo['desc']}")
    if todo.get("progress"):
        click.echo(f"Progress:  {todo['progress']}")
    for note in payload.get("notes") or []:
        if not isinstance(note, dict):
            continue
        click.echo(f"Note:      {note.get('note_id') or '-'}  {note.get('title') or '-'}")
        if summary:
            continue
        if note.get("content") is None:
            click.echo("Note snapshot is unreadable")
        elif note.get("content"):
            click.echo(note["content"])
    for chat in payload.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        title = chat.get("title") or ""
        label = chat.get("chat_id") or "-"
        click.echo(f"Chat:      {label}" + (f"  {title}" if title else ""))
        if not summary:
            _echo_messages(chat.get("messages"), full)
    for link in payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        click.echo(f"Link:      {link.get('activity_id') or '-'}  {link.get('title') or '-'}")
        if link.get("url"):
            click.echo(link["url"])
        if summary:
            continue
        if link.get("summary"):
            _echo_block("Summary:", link["summary"])
        if link.get("content"):
            _echo_block("Content:", link["content"])


@click.group("shared", invoke_without_command=True)
@click.pass_context
def todo_shared(ctx):
    """List or open todos other users have shared with you."""
    if ctx.invoked_subcommand is None:
        _print_shared()


@todo_shared.command("open")
@click.argument("share_id")
@click.option("--summary", is_flag=True, default=False, help="Show metadata and item ids/titles only.")
@click.option("--full", is_flag=True, default=False, help="Include stripped tool result placeholders in chats.")
def todo_shared_open(share_id, summary, full):
    """Open one shared todo by share id."""
    try:
        payload = api_request(
            "GET", "/api/todo/shared/detail", params={"share_id": share_id},
        ).json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(str(exc).split("\n", 1)[0]) from exc
    _render_shared_detail(payload, summary=summary, full=full)


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
