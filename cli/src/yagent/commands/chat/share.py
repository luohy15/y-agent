from typing import Optional
import click

from yagent.api_client import api_request


@click.command()
@click.option('--chat-id', '-c', help='ID of the chat to share')
@click.option('--latest', '-l', is_flag=True, help='Share the latest chat')
@click.option('--message-id', '-m', help='Share up to a specific message ID')
def share(chat_id: Optional[str], latest: bool, message_id: Optional[str]):
    """Share a chat conversation.

    Use --latest/-l to share your most recent chat.
    Use --chat-id/-c to share a specific chat ID.
    """
    if latest:
        resp = api_request("GET", "/api/chat/list", params={"limit": 1})
        chats = resp.json()
        if not chats:
            click.echo("Error: No chats found to share")
            raise click.Abort()
        chat_id = chats[0]["chat_id"]
    elif not chat_id:
        click.echo("Error: Chat ID is required for sharing")
        raise click.Abort()

    try:
        body: dict = {"chat_id": chat_id}
        if message_id:
            body["message_id"] = message_id
        resp = api_request("POST", "/api/chat/share", json=body)
        share_id = resp.json()["share_id"]
        click.echo(share_id)
    except Exception as e:
        click.echo(f"Error: {e}")
        raise click.Abort()
