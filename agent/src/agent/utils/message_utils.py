import json
from typing import Optional, List, Dict, Union
from storage.entity.dto import Message
from storage.util import generate_message_id, get_iso8601_timestamp, get_unix_timestamp

def create_message(role: str, content: str, reasoning_content: Optional[str] = None, provider: Optional[str] = None,
                   model: Optional[str] = None, id: Optional[str] = None, reasoning_effort: Optional[float] = None,
                   server: Optional[str] = None, tool: Optional[str] = None, arguments: Optional[Dict[str, Union[str, int, float, bool, Dict, List]]] = None,
                   links: Optional[List[str]] = None) -> Message:
    """Create a Message object with optional fields."""
    message_data = {
        "role": role,
        "content": content,
        "timestamp": get_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp()
    }

    if reasoning_content is not None:
        message_data["reasoning_content"] = reasoning_content

    if provider is not None:
        message_data["provider"] = provider

    if model is not None:
        message_data["model"] = model

    if id is not None:
        message_data["id"] = id

    if reasoning_effort is not None:
        message_data["reasoning_effort"] = reasoning_effort

    if server is not None:
        message_data["server"] = server

    if tool is not None:
        message_data["tool"] = tool

    if arguments is not None:
        message_data["arguments"] = arguments

    if links is not None:
        message_data["links"] = links

    return Message.from_dict(message_data)


def backfill_tool_results(messages: List[Message], mode: str = "rejected") -> List[Message]:
    """Backfill tool results for unhandled tool calls that lack responses.

    Args:
        messages: list of messages to backfill (mutated in-place)
        mode: "cancelled" backfills all unhandled tool calls as cancelled;
              "rejected" backfills only unhandled tool calls marked as "rejected".

    Returns the list of newly inserted tool messages.
    """
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
            "timestamp": get_iso8601_timestamp(),
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