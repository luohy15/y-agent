import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

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


@click.command('get')
@click.argument('chat_id')
def get_chat(chat_id: str):
    """Get a chat conversation by ID, showing user/assistant turns."""
    resp = api_request("GET", "/api/chat/content", params={"chat_id": chat_id})
    data = resp.json()

    turns = _extract_turns(data["messages"])

    if not turns:
        click.echo("No conversation turns found")
        return

    console = Console()
    for i, (user_msg, assistant_msg) in enumerate(turns, 1):
        console.print(Panel(Markdown(user_msg), title=f"[bold blue]User[/bold blue] ({i})", border_style="blue"))
        if assistant_msg:
            console.print(Panel(Markdown(assistant_msg), title=f"[bold green]Assistant[/bold green] ({i})", border_style="green"))
        console.print()
