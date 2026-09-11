import click
from yagent.api_client import api_request


@click.command("await")
@click.argument("todo_id")
@click.option("--chat", "chat_id", default=None, help="Same-owner same-trace public chat ID (navigation only)")
def todo_await(todo_id, chat_id):
    """Move a pending/active todo to awaiting, or replace its optional chat pointer."""
    body = {"todo_id": todo_id}
    if chat_id is not None:
        body["chat_id"] = chat_id
    resp = api_request("POST", "/api/todo/await", json=body)
    todo = resp.json()
    changed = todo.get("changed")
    if changed:
        pointer = f" chat={todo['awaiting_chat']}" if todo.get("awaiting_chat") else ""
        click.echo(f"Awaiting todo '{todo['name']}' ({todo['todo_id']}){pointer}")
    else:
        click.echo(f"Todo '{todo['name']}' ({todo['todo_id']}) already awaiting")
