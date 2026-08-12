import os

import click
import httpx

from yagent.api_client import api_request


@click.command("attention")
@click.argument("chat_id", required=False, default=None)
@click.option("--clear", is_flag=True, help="Clear the needs_attention signal instead of setting it.")
def chat_attention(chat_id: str | None, clear: bool):
    """Signal that this chat is blocked on Roy answering or confirming.

    Defaults to Y_CHAT_ID when CHAT_ID is omitted. A running session calls this
    right before it stops to wait for a reply; `--clear` reverses it explicitly
    (accepting a new user message into the chat also clears it automatically).
    """
    chat_id = chat_id or os.environ.get("Y_CHAT_ID")
    if not chat_id:
        click.echo("Error: CHAT_ID is required when Y_CHAT_ID is not set.", err=True)
        raise SystemExit(2)

    try:
        resp = api_request("POST", "/api/chat/attention", json={"chat_id": chat_id, "clear": clear})
        data = resp.json()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        click.echo(f"Error: {detail}", err=True)
        raise SystemExit(1)

    if clear:
        click.echo(f"cleared attention on chat {chat_id}")
    else:
        click.echo(f"marked chat {chat_id} needs_attention={data.get('needs_attention', True)}")
