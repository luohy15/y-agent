import os

import click
import httpx

from yagent.api_client import api_request


def _chat_id(explicit):
    chat_id = explicit or os.environ.get("Y_CHAT_ID")
    if not chat_id:
        raise click.UsageError("pass --chat-id or set Y_CHAT_ID")
    return chat_id


def _post(path, body):
    try:
        return api_request("POST", path, json=body)
    except httpx.HTTPStatusError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc


@click.command("claim")
@click.argument("todo_id")
@click.option("--chat-id", "chat_id", default=None, help="Coordinator chat id (default: $Y_CHAT_ID)")
@click.option("--takeover-from", default=None, help="Current owner chat id, required to seize a held claim")
def todo_claim(todo_id, chat_id, takeover_from):
    """Claim coordinator ownership of a todo."""
    body = {"todo_id": todo_id, "chat_id": _chat_id(chat_id)}
    if takeover_from:
        body["takeover_from"] = takeover_from
    resp = _post("/api/todo/claim", body)
    payload = resp.json()
    claim = payload.get("leader_claim") or {}
    click.echo(f"Leader: {payload.get('status')} by {claim.get('chat_id')}")


@click.command("release")
@click.argument("todo_id")
@click.option("--chat-id", "chat_id", default=None, help="Coordinator chat id (default: $Y_CHAT_ID)")
@click.option("--handoff", default=None, help="Short handoff written to progress (max 1000 characters)")
def todo_release(todo_id, chat_id, handoff):
    """Release coordinator ownership of a todo."""
    body = {"todo_id": todo_id, "chat_id": _chat_id(chat_id)}
    if handoff is not None:
        body["handoff"] = handoff
    resp = _post("/api/todo/release", body)
    payload = resp.json()
    click.echo(f"Leader: {payload.get('status')}")
