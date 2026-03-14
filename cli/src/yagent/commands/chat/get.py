import click

from yagent.api_client import api_request


def _extract_turns(messages: list) -> list:
    """Extract conversation turns: each turn is (user_content, assistant_content).

    Only keeps the last user and last assistant message content per turn.
    A turn starts with a user message and ends before the next user message.
    """
    turns = []
    current_user = None
    current_assistant = None

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        if role == "user":
            # Save previous turn if exists
            if current_user is not None:
                turns.append((current_user, current_assistant or ""))
            current_user = content
            current_assistant = None
        elif role == "assistant" and content.strip():
            current_assistant = content

    # Don't forget last turn
    if current_user is not None:
        turns.append((current_user, current_assistant or ""))

    return turns


def _print_chat(chat_id: str):
    """Fetch and print a single chat conversation."""
    resp = api_request("GET", "/api/chat/content", params={"chat_id": chat_id})
    data = resp.json()

    turns = _extract_turns(data["messages"])

    if not turns:
        click.echo(f"[{chat_id}] No conversation turns found")
        return

    for user_msg, assistant_msg in turns:
        click.echo(f"user: {user_msg.strip()}")
        if assistant_msg:
            click.echo(f"assistant: {assistant_msg.strip()}")


@click.command('get')
@click.argument('chat_ids', nargs=-1, required=True)
def get_chat(chat_ids: tuple):
    """Get chat conversations by ID, showing user/assistant turns."""
    for idx, chat_id in enumerate(chat_ids):
        if len(chat_ids) > 1:
            click.echo(f"====== Chat: {chat_id} ======")
        _print_chat(chat_id)
        if idx < len(chat_ids) - 1:
            click.echo()
