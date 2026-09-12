import click
from yagent.api_client import api_request

_STATUSES = ("pending", "active", "awaiting", "completed", "deleted")


@click.command("status")
@click.argument("todo_id")
@click.argument("status", type=click.Choice(_STATUSES, case_sensitive=True))
@click.option("--chat", "chat_id", default=None, help="Same-owner same-trace public chat ID (awaiting only)")
def todo_status(todo_id, status, chat_id):
    """Set a todo's status. --chat is valid only with awaiting and replaces the pointer."""
    if chat_id is not None and status != "awaiting":
        raise click.UsageError("--chat is only valid when status is awaiting")
    body = {"todo_id": todo_id, "status": status}
    if chat_id is not None:
        body["chat_id"] = chat_id
    resp = api_request("POST", "/api/todo/status", json=body)
    todo = resp.json()
    pointer = f" chat={todo['awaiting_chat']}" if todo.get("awaiting_chat") else ""
    click.echo(f"Todo '{todo['name']}' ({todo['todo_id']}): {todo['status']}{pointer}")
