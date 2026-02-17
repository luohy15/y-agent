"""Run a single chat through the agent loop, writing messages to DB."""

import os
from typing import List

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service

import agent.config as agent_config
from agent.loop import run_agent_loop
from agent.tools import get_tools_map, get_openai_tools


def message_callback(chat_id: str, message: Message):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message)


def check_auto_approve(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.auto_approve if c else False


def check_interrupted(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.interrupted if c else False


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, vm_name: str = None) -> None:
    """Execute a chat round. bot_name, user_id, and vm_name are passed from the queue message."""
    logger.info("run_chat start chat_id={} bot_name={} user_id={} vm_name={}", chat_id, bot_name, user_id, vm_name)

    # Load chat from DB (with user_id access check)
    chat = await chat_service.get_chat(user_id, chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return

    # Reset interrupted flag and mark as running
    chat.interrupted = False
    chat.running = True
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)

    bot_config = agent_config.resolve_bot_config(user_id, bot_name)
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)

    # Route to Claude Code worker or agent loop based on api_type
    try:
        if bot_config.api_type == "claude-code":
            await _run_chat_claude_code(chat, chat_id, user_id, bot_config, vm_name=vm_name)
        else:
            await _run_chat_agent_loop(chat, chat_id, user_id, bot_config, vm_name=vm_name)
    finally:
        # Mark chat as no longer running
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)


async def _run_chat_agent_loop(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None) -> None:
    """Run chat through the custom agent loop."""
    provider = agent_config.make_provider(bot_config)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name)
    tools_map = get_tools_map(vm_config)
    openai_tools = get_openai_tools(vm_config)
    system_prompt = await agent_config.build_system_prompt(vm_config)
    logger.info("Loaded {} tools, system_prompt length={}", len(tools_map), len(system_prompt) if system_prompt else 0)

    messages: List[Message] = list(chat.messages)
    logger.info("Loaded {} messages from chat {}", len(messages), chat_id)

    result = await run_agent_loop(
        provider=provider,
        messages=messages,
        system_prompt=system_prompt,
        tools_map=tools_map,
        openai_tools=openai_tools,
        message_callback=lambda msg: message_callback(chat_id, msg),
        auto_approve_fn=lambda: check_auto_approve(chat_id),
        check_interrupted_fn=lambda: check_interrupted(chat_id),
    )

    logger.info("run_chat finished chat_id={} status={}", chat_id, result.status)


async def _run_chat_claude_code(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None) -> None:
    """Run chat through Claude Code CLI with stateful session resume.

    First message creates a new session. Subsequent messages resume via
    session_id stored in chat.external_id.
    """
    from agent.claude_code import run_claude_code

    messages: List[Message] = list(chat.messages)
    logger.info("Loaded {} messages from chat {}", len(messages), chat_id)

    # Extract the latest user message as the prompt
    user_prompt = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not user_prompt:
        logger.error("No user message found in chat {}", chat_id)
        return

    vm_config = agent_config.resolve_vm_config(user_id, vm_name)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None  # treat empty string as None
    cb = lambda msg: message_callback(chat_id, msg)
    interrupted_fn = lambda: check_interrupted(chat_id)

    # Resume existing session or start new one
    session_id = chat.external_id
    resume = bool(session_id)
    logger.info("claude-code start chat_id={} session_id={} resume={}", chat_id, session_id, resume)

    result = await run_claude_code(
        prompt=user_prompt,
        message_callback=cb,
        cwd=cwd,
        session_id=session_id,
        resume=resume,
        last_message_id=last_message_id,
        check_interrupted_fn=interrupted_fn,
        model=model,
        vm_config=vm_config,
    )
    logger.info("claude-code done status={} session_id={} cost={}", result.status, result.session_id, result.cost_usd)

    # Save session_id to chat.external_id for future resume
    # Reload fresh chat from DB to avoid overwriting messages appended via callback
    if result.session_id:
        fresh_chat = await chat_service.get_chat_by_id(chat_id)
        if fresh_chat:
            fresh_chat.external_id = result.session_id
            from storage.repository import chat as chat_repo
            await chat_repo.save_chat_by_id(fresh_chat)

