"""Run a single chat through the agent loop, writing messages to DB."""

import json
from typing import List

from loguru import logger

from storage.entity.dto import BotConfig, Message
from storage.service import bot_config as bot_service, chat as chat_service
from storage.util import generate_message_id, get_iso8601_timestamp, get_unix_timestamp

from agent.loop import ApprovalNeeded, run_agent_loop
from agent.provider import OpenAIFormatProvider, AnthropicFormatProvider
from agent.tools import get_tools_map, get_openai_tools


def _make_provider(bot_config: BotConfig):
    if bot_config.api_type == "anthropic":
        return AnthropicFormatProvider(bot_config)
    return OpenAIFormatProvider(bot_config)


def _make_permission_callback(chat_id: str):
    """Permission callback that raises ApprovalNeeded to pause the loop."""

    async def permission_callback(tool_name: str, tool_args: dict) -> bool:
        raise ApprovalNeeded(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_calls=[],
            tool_call_index=0,
        )

    return permission_callback


def _build_system_prompt() -> str:
    from agent.skills import discover_skills, skills_to_prompt
    skills_block = skills_to_prompt(discover_skills())
    return ("\n" + skills_block) if skills_block else ""


def _resolve_bot_config(bot_name: str = None) -> BotConfig:
    bot_config = None
    if bot_name:
        bot_config = bot_service.get_config(bot_name)
    if not bot_config:
        bot_config = bot_service.get_config()
    return bot_config


async def run_chat(chat_id: str, status: str) -> None:
    """Execute a chat. Handles both fresh chats and resumed (approved/denied) chats."""
    logger.info("run_chat start chat_id={} status={}", chat_id, status)

    # Load chat from DB
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return

    bot_config = _resolve_bot_config(chat.bot_name)
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)
    provider = _make_provider(bot_config)

    tools_map = get_tools_map()
    openai_tools = get_openai_tools()
    system_prompt = _build_system_prompt()
    logger.info("Loaded {} tools, system_prompt length={}", len(tools_map), len(system_prompt) if system_prompt else 0)

    # Sync callback for agent loop (which calls display_callback without await)
    def display_callback(message: Message):
        logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
        chat_service.append_message_sync(chat_id, message)

    # Load messages from chat
    messages: List[Message] = list(chat.messages)
    logger.info("Loaded {} messages from chat {}", len(messages), chat_id)

    # --- Handle approval from a previous run ---
    if status in ("approved", "denied"):
        approved = (status == "approved")
        await chat_service.update_chat_status(chat_id, "running")

        # Find the last assistant message with tool info
        last_assistant = None
        for m in reversed(messages):
            if m.role == "assistant" and m.tool:
                last_assistant = m
                break

        if last_assistant and last_assistant.tool:
            # Reconstruct tool call from message fields (since _raw_tool_calls doesn't survive DB)
            full_tool_calls = [{
                "id": f"call_{last_assistant.id}",
                "type": "function",
                "function": {
                    "name": last_assistant.tool,
                    "arguments": json.dumps(last_assistant.arguments or {}),
                },
            }]

            # Count existing tool responses after this assistant message
            assistant_idx = None
            for i, m in enumerate(messages):
                if m.id and m.id == last_assistant.id:
                    assistant_idx = i
                    break

            existing_tool_responses = 0
            if assistant_idx is not None:
                for m in messages[assistant_idx + 1:]:
                    if m.role == "tool":
                        existing_tool_responses += 1

            tc_start = existing_tool_responses

            for i in range(tc_start, len(full_tool_calls)):
                tc = full_tool_calls[i]
                func = tc["function"]
                tn = func["name"]
                try:
                    ta = json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    ta = {}

                if i == tc_start:
                    if approved:
                        tool = tools_map.get(tn)
                        result = await tool.execute(ta) if tool else f"Unknown tool: {tn}"
                    else:
                        result = f"ERROR: User denied execution of {tn} with args {ta}. The command was NOT executed. Do NOT proceed as if it succeeded."
                else:
                    tool = tools_map.get(tn)
                    result = await tool.execute(ta) if tool else f"Unknown tool: {tn}"

                logger.info("Tool call [{}] {} result_length={}", i, tn, len(result))

                if len(result) > 10000:
                    result = result[:10000] + "\n... (truncated)"

                tool_msg = Message.from_dict({
                    "role": "tool",
                    "content": result,
                    "timestamp": get_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "parent_id": last_assistant.id,
                    "tool": tn,
                })
                tool_msg._tool_call_id = tc["id"]
                display_callback(tool_msg)
                messages.append(tool_msg)

    # --- Run agent loop ---
    try:
        logger.info("Starting agent loop with {} messages", len(messages))
        await run_agent_loop(
            provider=provider,
            messages=messages,
            system_prompt=system_prompt,
            tools_map=tools_map,
            openai_tools=openai_tools,
            display_callback=display_callback,
            permission_callback=_make_permission_callback(chat_id),
        )
        # Completed normally
        logger.info("Agent loop completed for chat {}", chat_id)
        await chat_service.save_messages(chat_id, messages)
        await chat_service.update_chat_status(chat_id, "completed")

    except ApprovalNeeded as e:
        logger.info("Approval needed for chat {}: tool={}", chat_id, e.tool_name)
        # Save all messages (including the assistant message with tool info)
        await chat_service.save_messages(chat_id, messages)
        await chat_service.update_chat_status(chat_id, "waiting_approval")

    except Exception as e:
        logger.exception("Agent loop failed for chat {}", chat_id)
        await chat_service.save_messages(chat_id, messages)
        await chat_service.update_chat_status(chat_id, "failed")
