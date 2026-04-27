import os
import sys
import click
import httpx
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


def _fire_and_forget(
    message: str,
    topic: Optional[str],
    skill: Optional[str],
    chat_id: Optional[str],
    work_dir: Optional[str],
    trace_id: Optional[str],
    force_new: bool,
    from_topic: str,
    from_chat_id: Optional[str],
    backend: Optional[str],
):
    """POST a message to /api/notify and print the resulting chat_id."""
    if not from_chat_id:
        from_chat_id = os.environ.get('Y_CHAT_ID')

    payload = {
        "message": message,
        "force_new": force_new,
        "from_topic": from_topic,
    }
    if topic:
        payload["topic"] = topic
    if skill:
        payload["skill"] = skill
    if chat_id:
        payload["chat_id"] = chat_id
    if trace_id:
        payload["trace_id"] = trace_id
    if work_dir:
        payload["work_dir"] = work_dir
    if from_chat_id:
        payload["from_chat_id"] = from_chat_id
    if backend:
        payload["backend"] = backend
    try:
        resp = api_request("POST", "/api/notify", json=payload)
        data = resp.json()
        click.echo(data["chat_id"])
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        click.echo(f"Error: {detail}", err=True)
        raise SystemExit(1)


def _interactive(
    chat_id: Optional[str],
    latest: bool,
    bot: Optional[str],
    prompt: Optional[str],
):
    """Interactive REPL (or one-off with -p)."""
    display_manager = DisplayManager()
    input_manager = InputManager(display_manager.console)
    work_dir = os.getcwd()

    if latest:
        resp = api_request("GET", "/api/chat/list", params={"limit": 1})
        chats = resp.json()
        if not chats:
            click.echo("Error: No existing chats found")
            raise click.Abort()
        chat_id = chats[0]["chat_id"]

    last_index = 0
    if chat_id:
        last_index, interrupted = _stream_and_handle(chat_id, display_manager, last_index=0)
        if interrupted:
            return

    if prompt:
        if chat_id:
            api_request("POST", "/api/chat/message", json={"chat_id": chat_id, "prompt": prompt, "bot_name": bot, "work_dir": work_dir})
        else:
            resp = api_request("POST", "/api/chat", json={"prompt": prompt, "bot_name": bot, "work_dir": work_dir})
            chat_id = resp.json()["chat_id"]

        _stream_and_handle(chat_id, display_manager, last_index)
        return

    while True:
        try:
            user_input, is_multiline, num_lines = input_manager.get_input()
        except KeyboardInterrupt:
            break

        if input_manager.is_exit_command(user_input):
            break

        if not user_input:
            continue

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


@click.group('chat', invoke_without_command=True)
# Shared
@click.option('--chat-id', '-c', default=None, help='Target an existing chat')
# Fire-and-forget (default top-level mode)
@click.option('--message', '-m', default=None, help='Message to send (fire-and-forget)')
@click.option('--topic', default=None, help='Target topic (named persistent address)')
@click.option('--skill', default=None, help='Skill to load on the target chat (defaults to topic for non-manager topics)')
@click.option('--work-dir', default=None, help='Working directory for the chat')
@click.option('--trace-id', default=None, help='Trace ID')
@click.option('--new', 'force_new', is_flag=True, help='Force create a new chat instead of resuming existing one')
@click.option('--from-topic', default='manager', help='Caller topic name (default: manager)')
@click.option('--from-chat-id', default=None, help='Caller chat ID (defaults to Y_CHAT_ID env var)')
@click.option('--backend', default=None, type=click.Choice(['claude_code', 'codex'], case_sensitive=False), help='Backend to use (default: claude_code)')
# Interactive REPL (-i mode)
@click.option('--interactive', '-i', is_flag=True, help='Open the interactive REPL')
@click.option('--latest', '-l', is_flag=True, help='[interactive] Continue from the latest chat')
@click.option('--bot', '-b', default=None, help='[interactive] Use specific bot name')
@click.option('--prompt', '-p', default=None, help='[interactive] Run a one-off query and exit')
@click.pass_context
def chat_group(
    ctx,
    chat_id: Optional[str],
    message: Optional[str],
    topic: Optional[str],
    skill: Optional[str],
    work_dir: Optional[str],
    trace_id: Optional[str],
    force_new: bool,
    from_topic: str,
    from_chat_id: Optional[str],
    backend: Optional[str],
    interactive: bool,
    latest: bool,
    bot: Optional[str],
    prompt: Optional[str],
):
    """Chat with AI models.

    Top-level (no subcommand) supports two modes:

    \b
      Fire-and-forget (default — like the old `y notify`):
        y chat -m "..."                          fresh anonymous chat
        y chat --topic dev -m "..."              named-address chat
        y chat --topic dev --skill review -m "." topic + explicit skill
        y chat --skill dev -m "..."              anonymous chat with skill
        y chat --chat-id <id> -m "..."           continue an existing chat

    \b
      Interactive REPL:
        y chat -i                                new interactive chat
        y chat -i -l                             resume the latest chat
        y chat -i -c <id>                        resume a specific chat
        y chat -i -p "..."                       one-off query and exit

    Subcommands (`get`, `list`, `search`, `share`, `import`, `import-claude`,
    `stop`) are unchanged.
    """
    if ctx.invoked_subcommand is not None:
        return

    if message is not None and interactive:
        click.echo("Error: -m and -i are mutually exclusive.", err=True)
        raise SystemExit(2)

    if message is not None:
        _fire_and_forget(
            message=message,
            topic=topic,
            skill=skill,
            chat_id=chat_id,
            work_dir=work_dir,
            trace_id=trace_id,
            force_new=force_new,
            from_topic=from_topic,
            from_chat_id=from_chat_id,
            backend=backend,
        )
        return

    if interactive:
        _interactive(chat_id=chat_id, latest=latest, bot=bot, prompt=prompt)
        return

    click.echo("Error: pass -m <message> for fire-and-forget, or -i for the interactive REPL.", err=True)
    click.echo(ctx.get_help())
    raise SystemExit(2)


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
