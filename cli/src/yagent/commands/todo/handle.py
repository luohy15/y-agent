import click
from yagent.api_client import api_request


@click.command("handle")
@click.argument("todo_id")
@click.option("--chat", "chat_id", required=True, help="Same-owner same-todo conversation chat ID")
def todo_handle(todo_id, chat_id):
    """Set the durable conversation handle for an open todo."""
    todo = api_request("POST", "/api/todo/handle", json={
        "todo_id": todo_id, "chat_id": chat_id,
    }).json()
    click.echo(f"Todo {todo['todo_id']}: handle {todo['handle_chat']}")
