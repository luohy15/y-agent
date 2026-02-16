import json
import os
import sys
import tty
import termios
from typing import List, Optional

from loguru import logger
from rich.console import Console

from storage.entity.dto import Chat, Message
from storage.service import chat as chat_service
from storage.service.user import get_cli_user_id
from storage.util import generate_id, generate_message_id, backfill_tool_results
from yagent.display_manager import DisplayManager
from yagent.input_manager import InputManager

import agent.config as agent_config
from agent.loop import run_agent_loop
from agent.tools import get_tools_map, get_openai_tools
from .provider.base_provider import BaseProvider
from .utils.message_utils import create_message


def handle_message(display_manager: DisplayManager, chat_id: str, message: Message):
    display_manager.display_message_panel(message)
    chat_service.append_message_sync(chat_id, message)


async def ensure_chat(chat_id: str, messages: List[Message], current_chat: Optional[Chat]) -> Chat:
    if not current_chat:
        current_chat = await chat_service.create_chat(get_cli_user_id(), messages, chat_id=chat_id)
    return current_chat


def save_messages(chat_id: str, messages: List[Message], current_chat: Optional[Chat]):
    if current_chat:
        chat_service.save_messages_sync(chat_id, messages)


def _display_recent_messages(display_manager: DisplayManager, messages: List[Message], rounds: int = 5):
    """Display the last N rounds of messages. A round starts with a user message."""
    # Find indices of user messages to determine round boundaries
    user_indices = [i for i, m in enumerate(messages) if m.role == "user"]
    if not user_indices:
        return

    # Take the last `rounds` user message start points
    start_idx = user_indices[-rounds] if len(user_indices) >= rounds else 0
    for msg in messages[start_idx:]:
        display_manager.display_message_panel(msg)


def _has_pending_tools(messages: List[Message]) -> bool:
    """Check if the last assistant message has pending tool calls."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "assistant" and messages[i].tool_calls:
            return any(tc.get("status") == "pending" for tc in messages[i].tool_calls)
    return False


def _prompt_tool_approval(console: Console, messages: List[Message]) -> tuple[bool, Optional[str]]:
    """Prompt user to approve/reject each pending tool_call in the last assistant message.
    Returns (interrupted, user_message). interrupted=True means Ctrl-C.
    user_message is set when user denies with a message (d option)."""
    # Find last assistant message with tool_calls
    last_assistant = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "assistant" and messages[i].tool_calls:
            last_assistant = messages[i]
            break

    if not last_assistant:
        return False, None

    for tc in last_assistant.tool_calls:
        if tc.get("status") != "pending":
            continue

        func = tc["function"]
        tool_name = func["name"]
        try:
            tool_args = json.loads(func["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_args = {}

        args_str = json.dumps(tool_args, separators=(',', ':'))
        if len(args_str) > 200:
            args_str = args_str[:200] + '...'
        console.print(f"[yellow]Tool call: {tool_name}({args_str})[/yellow] [dim]Allow? \\[y/n/s(kip all)/d(eny with msg)][/dim] ", end="")

        # Read single keypress without Enter
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1).lower()
        except KeyboardInterrupt:
            ch = '\x03'
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        def _reject_all_pending():
            tc["status"] = "rejected"
            for remaining_tc in last_assistant.tool_calls:
                if remaining_tc.get("status") == "pending":
                    remaining_tc["status"] = "rejected"

        if ch == '\x03':  # Ctrl-C: reject all and interrupt
            console.print("[red]interrupted[/red]")
            _reject_all_pending()
            return True, None

        if ch == 's':  # Skip all: reject all remaining pending tools
            console.print("[red]skip all[/red]")
            _reject_all_pending()
            return False, None

        if ch == 'd':  # Deny with message: reject all and prompt for user message
            console.print("[red]deny with message[/red]")
            _reject_all_pending()
            console.print("[dim]Enter message:[/dim] ", end="")
            try:
                user_msg = input()
            except (KeyboardInterrupt, EOFError):
                return True, None
            return False, user_msg or None

        if ch == 'y':
            tc["status"] = "approved"
            console.print("[green]y[/green]")
        else:
            tc["status"] = "rejected"
            console.print("[red]n[/red]")

    return False, None


async def run_round(
    display_manager: DisplayManager,
    chat_id: str,
    messages: List[Message],
    current_chat: Optional[Chat],
    provider: BaseProvider,
    tools_map: dict,
    openai_tools: list,
    auto_approve_state: list = None,
):
    while True:
        result = await run_agent_loop(
            provider=provider,
            messages=messages,
            system_prompt=await agent_config.build_system_prompt(),
            tools_map=tools_map,
            openai_tools=openai_tools,
            message_callback=lambda msg: handle_message(display_manager, chat_id, msg),
            auto_approve_fn=lambda: auto_approve_state[0] if auto_approve_state else False,
        )
        save_messages(chat_id, messages, current_chat)

        if result.status != "approval_needed":
            if result.status == "interrupted":
                backfill_tool_results(messages, mode="cancelled")
                save_messages(chat_id, messages, current_chat)
            return

        interrupted, user_msg = _prompt_tool_approval(display_manager.console, messages)
        backfill_tool_results(messages, mode="rejected")
        save_messages(chat_id, messages, current_chat)
        if interrupted:
            return

        if user_msg:
            user_message = create_message("user", user_msg, id=generate_message_id())
            messages.append(user_message)
            handle_message(display_manager, chat_id, user_message)


async def run_chat(
    display_manager: DisplayManager,
    input_manager: InputManager,
    provider: BaseProvider,
    chat_id: Optional[str] = None,
    verbose: bool = False,
    prompt: Optional[str] = None,
):
    vm_config = agent_config.resolve_vm_config(get_cli_user_id())
    vm_config.work_dir = os.getcwd()
    tools_map = get_tools_map(vm_config)
    openai_tools = get_openai_tools(vm_config)

    messages: List[Message] = []
    current_chat: Optional[Chat] = None
    # Mutable container so lambda in run_round sees current value
    auto_approve_state = [False]

    # Load existing chat or generate new ID
    if chat_id:
        existing_chat = await chat_service.get_chat(get_cli_user_id(), chat_id)
        if not existing_chat:
            display_manager.print_error(f"Chat {chat_id} not found")
            raise ValueError(f"Chat {chat_id} not found")
        messages = list(existing_chat.messages)
        current_chat = existing_chat
        auto_approve_state[0] = existing_chat.auto_approve
        if verbose:
            logger.info(f"Loaded {len(messages)} messages from chat {chat_id}")

        # Display recent messages (last 5 rounds)
        _display_recent_messages(display_manager, messages, rounds=5)

        # If last assistant message has pending tool calls, resume tool approval flow
        if _has_pending_tools(messages):
            interrupted, user_msg = _prompt_tool_approval(display_manager.console, messages)
            backfill_tool_results(messages, mode="rejected")
            save_messages(chat_id, messages, current_chat)
            if user_msg:
                user_message = create_message("user", user_msg, id=generate_message_id())
                messages.append(user_message)
                handle_message(display_manager, chat_id, user_message)
            if not interrupted:
                await run_round(display_manager, chat_id, messages, current_chat, provider, tools_map, openai_tools, auto_approve_state=auto_approve_state)
    else:
        chat_id = generate_id()

    assert chat_id is not None

    # Process initial prompt if provided
    if prompt:
        user_message = create_message("user", prompt, id=generate_message_id())
        messages.append(user_message)
        current_chat = await ensure_chat(chat_id, messages, current_chat)
        await run_round(display_manager, chat_id, messages, current_chat, provider, tools_map, openai_tools, auto_approve_state=auto_approve_state)
        return

    # Continue with follow-up rounds
    while True:
        try:
            user_input, is_multiline, num_lines = input_manager.get_input()
        except (KeyboardInterrupt):
            break

        if input_manager.is_exit_command(user_input):
            break

        if not user_input:
            continue

        # Handle /auto command to toggle auto-approve
        if user_input.strip().lower() == "/auto":
            auto_approve_state[0] = not auto_approve_state[0]
            status = "ON" if auto_approve_state[0] else "OFF"
            display_manager.console.print(f"[yellow]Auto-approve: {status}[/yellow]")
            continue

        # Clear input lines and redisplay user input in a panel
        clear_lines = num_lines + 2 if is_multiline else 1
        sys.stdout.write("\033[A\033[2K" * clear_lines)
        sys.stdout.flush()
        user_message = create_message("user", user_input)
        messages.append(user_message)
        current_chat = await ensure_chat(chat_id, messages, current_chat)
        handle_message(display_manager, chat_id, user_message)

        await run_round(display_manager, chat_id, messages, current_chat, provider, tools_map, openai_tools, auto_approve_state=auto_approve_state)
