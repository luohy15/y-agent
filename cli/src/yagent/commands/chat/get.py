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


def _print_chat(chat_id: str, full: bool = False):
    """Fetch and print a single chat conversation."""
    resp = api_request("GET", "/api/chat/content", params={"chat_id": chat_id})
    data = resp.json()

    if full:
        _print_full(data["messages"])
    else:
        turns = _extract_turns(data["messages"])

        if not turns:
            click.echo(f"[{chat_id}] No conversation turns found")
            return

        for user_msg, assistant_msg in turns:
            click.echo(f"user: {user_msg.strip()}")
            if assistant_msg:
                click.echo(f"assistant: {assistant_msg.strip()}")


def _format_tool_calls(tool_calls: list) -> str:
    """Format tool_calls into a readable string."""
    parts = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "unknown")
        args = func.get("arguments", "")
        if isinstance(args, str):
            import json as _json
            try:
                args = _json.loads(args)
            except (ValueError, TypeError):
                args = {}
        cmd = args.get("command") or args.get("description") or ""
        if cmd:
            parts.append(f"{name}({cmd})")
        else:
            parts.append(name)
    return ", ".join(parts)


def _print_full(messages: list):
    """Print all messages with their roles."""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        tool_name = msg.get("tool")
        tool_calls = msg.get("tool_calls")

        # Build role label with tool info
        label = role
        if role == "tool" and tool_name:
            args = msg.get("arguments") or {}
            cmd = args.get("command") or args.get("description") or ""
            label = f"tool({tool_name}: {cmd})" if cmd else f"tool({tool_name})"
        elif role == "assistant" and tool_calls:
            label = f"assistant -> {_format_tool_calls(tool_calls)}"

        if isinstance(content, str) and content.strip():
            click.echo(f"{label}: {content.strip()}")
        elif tool_calls:
            click.echo(f"{label}")
        elif role == "tool" and tool_name:
            click.echo(f"{label}: (no output)")


@click.command('get')
@click.argument('chat_ids', nargs=-1, required=True)
@click.option('--full', is_flag=True, default=False, help='Show all messages, not just user/assistant turns.')
def get_chat(chat_ids: tuple, full: bool):
    """Get chat conversations by ID, showing user/assistant turns."""
    for idx, chat_id in enumerate(chat_ids):
        if len(chat_ids) > 1:
            click.echo(f"====== Chat: {chat_id} ======")
        _print_chat(chat_id, full=full)
        if idx < len(chat_ids) - 1:
            click.echo()
