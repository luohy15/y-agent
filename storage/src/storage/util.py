import json
import time
from typing import List
from loguru import logger

def get_unix_timestamp() -> int:
    """Get current time as 13-digit unix timestamp (milliseconds)"""
    return int(time.time() * 1000)

def get_utc_iso8601_timestamp() -> str:
    """Get current UTC time as ISO 8601 string with ms precision and Z suffix.
    Example: '2025-04-28T04:08:29.568Z'
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

def generate_id() -> str:
    """Generate a unique ID (6 characters)"""
    import uuid
    return uuid.uuid4().hex[:6]

def generate_message_id() -> str:
    """Generate a unique message ID in format msg_{timestamp}_{random8chars}"""
    import random
    import string
    chars = string.ascii_lowercase + string.digits
    rand = ''.join(random.choices(chars, k=8))
    return f"msg_{int(time.time() * 1000)}_{rand}"


def build_message_path(messages: List, message_id: str) -> List:
    """Traverse parent_id from a given message back to root, returning messages forming the conversation path."""
    msg_map = {}
    for msg in messages:
        if msg.id:
            msg_map[msg.id] = msg

    logger.debug("build_message_path: starting from {}, {} messages in map", message_id, len(msg_map))

    path = []
    visited = set()
    current_id = message_id
    max_steps = 20
    while current_id and current_id in msg_map and len(path) < max_steps:
        if current_id in visited:
            logger.warning("build_message_path: cycle detected at {}, breaking", current_id)
            break
        visited.add(current_id)
        msg = msg_map[current_id]
        path.append(msg)
        logger.debug("build_message_path: {} -> parent {}", current_id, msg.parent_id)
        current_id = msg.parent_id

    path.reverse()
    logger.debug("build_message_path: result path has {} messages", len(path))
    return path


def backfill_tool_results(messages: List, mode: str = "rejected") -> List:
    """Backfill tool results for unhandled tool calls that lack responses.

    Args:
        messages: list of messages to backfill (mutated in-place)
        mode: "cancelled" backfills all unhandled tool calls as cancelled;
              "rejected" backfills only unhandled tool calls marked as "rejected".

    Returns the list of newly inserted tool messages.
    """
    from storage.entity.dto import Message

    # Find last assistant message with tool_calls
    last_assistant = None
    last_assistant_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "assistant" and messages[i].tool_calls:
            last_assistant = messages[i]
            last_assistant_idx = i
            break

    if not last_assistant or not last_assistant.tool_calls:
        return []

    # Collect existing tool responses
    existing_tool_ids = set()
    for m in messages[last_assistant_idx + 1:]:
        if m.role == "tool" and m.tool_call_id:
            existing_tool_ids.add(m.tool_call_id)

    unhandled = [tc for tc in last_assistant.tool_calls if tc["id"] not in existing_tool_ids]
    # When rejected, only backfill tool calls explicitly marked as "rejected"
    if mode == "rejected":
        unhandled = [tc for tc in unhandled if tc.get("status") == "rejected"]
    if not unhandled:
        return []

    # Insert results after existing tool responses
    insert_idx = last_assistant_idx + 1
    while insert_idx < len(messages) and messages[insert_idx].role == "tool":
        insert_idx += 1
    tool_msgs = []
    for tc in unhandled:
        func = tc["function"]
        tool_name = func["name"]
        try:
            tool_args = json.loads(func["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_args = {}

        if mode == "rejected":
            content = f"ERROR: User denied execution of {tool_name} with args {tool_args}. The command was NOT executed. Do NOT proceed as if it succeeded."
        else:
            content = f"ERROR: Execution of {tool_name} was cancelled due to interruption. The command was NOT executed."
            tc["status"] = "cancelled"

        tool_msg = Message.from_dict({
            "role": "tool",
            "content": content,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "parent_id": last_assistant.id,
            "tool": tool_name,
            "arguments": tool_args,
            "tool_call_id": tc["id"],
        })
        tool_msgs.append(tool_msg)

    for offset, msg in enumerate(tool_msgs):
        messages.insert(insert_idx + offset, msg)

    return tool_msgs
