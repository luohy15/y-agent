import os
import sys
import click
from typing import Optional

from yagent.api_client import api_request
from yagent.chat.stream_client import stream_chat
from yagent.display_manager import DisplayManager
from yagent.input_manager import InputManager


def _stop_chat(chat_id: str):
    try:
        api_request("POST", "/api/chat/stop", json={"chat_id": chat_id})
    except Exception:
        pass


def _stream_and_handle(chat_id: str, display_manager: DisplayManager, last_index: int = 0):
    """Stream messages. Returns (last_index, interrupted)."""
    try:
        last_index, status, data = stream_chat(chat_id, display_manager, last_index)
    except KeyboardInterrupt:
        _stop_chat(chat_id)
        return last_index, True

    if status == "interrupted":
        _stop_chat(chat_id)
        return last_index, True

    if status == "done":
        return last_index, False

    return last_index, True


@click.group('chat', invoke_without_command=True)
@click.option('--chat-id', '-c', help='Continue from an existing chat')
@click.option('--latest', '-l', is_flag=True, help='Continue from the latest chat')
@click.option('--bot', '-b', help='Use specific bot name')
@click.option('--prompt', '-p', help='Run a one-off query and exit')
@click.pass_context
def chat_group(ctx, chat_id: Optional[str], latest: bool, bot: Optional[str] = None, prompt: Optional[str] = None):
    """Chat with AI models."""
    if ctx.invoked_subcommand is not None:
        return

    display_manager = DisplayManager()
    input_manager = InputManager(display_manager.console)
    work_dir = os.getcwd()

    # Handle --latest flag
    if latest:
        resp = api_request("GET", "/api/chat/list", params={"limit": 1})
        chats = resp.json()
        if not chats:
            click.echo("Error: No existing chats found")
            raise click.Abort()
        chat_id = chats[0]["chat_id"]

    # Continuing existing chat: catch up via SSE
    last_index = 0
    if chat_id:
        last_index, interrupted = _stream_and_handle(chat_id, display_manager, last_index=0)
        if interrupted:
            return

    # Process initial prompt if provided (one-off or new chat)
    if prompt:
        if chat_id:
            # Follow-up message on existing chat
            api_request("POST", "/api/chat/message", json={"chat_id": chat_id, "prompt": prompt, "bot_name": bot, "work_dir": work_dir})
        else:
            # New chat
            resp = api_request("POST", "/api/chat", json={"prompt": prompt, "bot_name": bot, "work_dir": work_dir})
            chat_id = resp.json()["chat_id"]

        _stream_and_handle(chat_id, display_manager, last_index)
        return

    # Interactive mode
    while True:
        try:
            user_input, is_multiline, num_lines = input_manager.get_input()
        except KeyboardInterrupt:
            break

        if input_manager.is_exit_command(user_input):
            break

        if not user_input:
            continue

        # Clear input lines and redisplay
        clear_lines = num_lines + 2 if is_multiline else 1
        sys.stdout.write("\033[A\033[2K" * clear_lines)
        sys.stdout.flush()

        if chat_id:
            api_request("POST", "/api/chat/message", json={"chat_id": chat_id, "prompt": user_input, "bot_name": bot, "work_dir": work_dir})
        else:
            resp = api_request("POST", "/api/chat", json={"prompt": user_input, "bot_name": bot, "work_dir": work_dir})
            chat_id = resp.json()["chat_id"]

        last_index, interrupted = _stream_and_handle(chat_id, display_manager, last_index)
        if interrupted:
            break


from .list import list_chats
from .share import share
from .import_chat import import_chats
from .import_claude import import_claude
from .search import search_chats
from .get import get_chat
from .stop import stop_chat

chat_group.add_command(list_chats)
chat_group.add_command(share)
chat_group.add_command(import_chats)
chat_group.add_command(import_claude)
chat_group.add_command(search_chats)
chat_group.add_command(get_chat)
chat_group.add_command(stop_chat)
