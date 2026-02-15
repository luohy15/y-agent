"""Run a single chat through the agent loop, writing messages to DB."""

from typing import List

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service
from storage.util import backfill_tool_results

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


async def run_chat(user_id: int, chat_id: str, bot_name: str = None) -> None:
    """Execute a chat round. bot_name and user_id are passed from the queue message."""
    logger.info("run_chat start chat_id={} bot_name={} user_id={}", chat_id, bot_name, user_id)

    # Load chat from DB (with user_id access check)
    chat = await chat_service.get_chat(user_id, chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return

    # Reset interrupted flag so it doesn't persist across runs
    chat.interrupted = False
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)

    bot_config = agent_config.resolve_bot_config(user_id, bot_name)
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)
    provider = agent_config.make_provider(bot_config)

    vm_config = agent_config.resolve_vm_config(user_id)
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
