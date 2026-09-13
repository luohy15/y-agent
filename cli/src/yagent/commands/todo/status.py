import click
from yagent.api_client import api_request

_STATUSES = ("pending", "active", "awaiting", "completed", "deleted")


@click.command("status")
@click.argument("todo_id")
@click.argument("status", type=click.Choice(_STATUSES, case_sensitive=True))
@click.option("--chat", "chat_id", default=None, help="Same-owner same-trace public chat ID (awaiting only)")
@click.option("--note", "notice", default=None, help="One-sentence context for the attention DM (awaiting only)")
def todo_status(todo_id, status, chat_id, notice):
    """Set a todo's status. --chat and --note are valid only with awaiting."""
    if chat_id is not None and status != "awaiting":
        raise click.UsageError("--chat is only valid when status is awaiting")
    if notice is not None and status != "awaiting":
        raise click.UsageError("--note is only valid when status is awaiting")
    if notice is not None and not " ".join(notice.split()):
        raise click.UsageError("--note must be a non-empty sentence")
    body = {"todo_id": todo_id, "status": status}
    if chat_id is not None:
        body["chat_id"] = chat_id
    if notice is not None:
        body["notice"] = notice
    resp = api_request("POST", "/api/todo/status", json=body)
    todo = resp.json()
    pointer = f" chat={todo['awaiting_chat']}" if todo.get("awaiting_chat") else ""
    click.echo(f"Todo '{todo['name']}' ({todo['todo_id']}): {todo['status']}{pointer}")
    if status == "awaiting" and notice is None:
        click.echo("No --note supplied; the attention DM will have no context line.")
