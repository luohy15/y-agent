"""Run a single chat through the agent loop, writing messages to DB."""

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


async def run_chat(chat_id: str, bot_name: str = None) -> None:
    """Execute a chat round. bot_name is passed from the queue message."""
    logger.info("run_chat start chat_id={} bot_name={}", chat_id, bot_name)

    # Load chat from DB
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return

    bot_config = agent_config.resolve_bot_config(bot_name)
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)
    provider = agent_config.make_provider(bot_config)

    tools_map = get_tools_map()
    openai_tools = get_openai_tools()
    system_prompt = agent_config.build_system_prompt()
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
    )

    # Re-save all messages to persist in-place mutations (e.g. tool_call statuses)
    chat_service.save_messages_sync(chat_id, messages)

    logger.info("run_chat finished chat_id={} status={}", chat_id, result.status)
