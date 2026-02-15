import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from storage.entity.dto import Message
from storage.util import generate_message_id, get_iso8601_timestamp, get_unix_timestamp
from agent.permissions import PermissionManager


class ClientError(Exception):
    """Raised when the LLM API returns a 4xx client error (non-retryable)."""
    pass


class InterruptedError(Exception):
    """Raised when the agent loop is interrupted via check_interrupted_fn."""
    pass


@dataclass
class LoopResult:
    status: str  # "completed" | "approval_needed" | "interrupted" | "error" | "max_iterations"


def _default_display(message: Message):
    """Fallback plain-text display."""
    if message.role == "assistant":
        print(message.content)
    elif message.role == "tool" and message.tool:
        result = message.content
        print(f"[tool_result] {message.tool}: {result[:200]}{'...' if len(result) > 200 else ''}")



async def _run_tool_calls(
    messages: List[Message],
    tools_map: Dict,
    message_callback: Callable[[Message], None],
) -> Optional[LoopResult]:
    """Execute unhandled tool_calls on the last assistant message.

    Returns None if all tool_calls were executed (or nothing to do).
    Returns LoopResult if the loop should exit (approval_needed).
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
        return None

    # Collect existing tool responses
    existing_tool_ids = set()
    for m in messages[last_assistant_idx + 1:]:
        if m.role == "tool" and m.tool_call_id:
            existing_tool_ids.add(m.tool_call_id)

    unhandled = [tc for tc in last_assistant.tool_calls if tc["id"] not in existing_tool_ids]
    if not unhandled:
        return None

    # Still waiting for user approval
    pending_tc = next((tc for tc in unhandled if tc.get("status") == "pending"), None)
    if pending_tc:
        return LoopResult("approval_needed")

    # Execute approved/rejected tool_calls
    for tc in unhandled:
        func = tc["function"]
        tool_name = func["name"]
        try:
            tool_args = json.loads(func["arguments"])
        except (json.JSONDecodeError, TypeError):
            tool_args = {}

        status = tc.get("status", "approved")
        if status == "rejected":
            result = f"ERROR: User denied execution of {tool_name} with args {tool_args}. The command was NOT executed. Do NOT proceed as if it succeeded."
        else:
            tool = tools_map.get(tool_name)
            result = await tool.execute(tool_args) if tool else f"Unknown tool: {tool_name}"

        if len(result) > 10000:
            result = result[:10000] + "\n... (truncated)"

        tool_msg = Message.from_dict({
            "role": "tool",
            "content": result,
            "timestamp": get_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "parent_id": last_assistant.id,
            "tool": tool_name,
            "arguments": tool_args,
            "tool_call_id": tc["id"],
        })
        message_callback(tool_msg)
        messages.append(tool_msg)

    return None



async def run_agent_loop(
    provider,
    messages: List[Message],
    system_prompt: Optional[str],
    tools_map: Dict,
    openai_tools: List[Dict],
    max_iterations: int = 50,
    permission_manager: Optional[PermissionManager] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    auto_approve_fn: Optional[Callable[[], bool]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
) -> LoopResult:
    """Run the agent loop: call LLM, execute tool calls, repeat until plain text.

    Returns a LoopResult indicating how the loop exited.
    """
    if permission_manager is None:
        permission_manager = PermissionManager()
    if message_callback is None:
        message_callback = _default_display

    # Wrap message_callback to check interrupted before persisting
    original_callback = message_callback
    def message_callback_with_interrupt_check(msg: Message):
        if check_interrupted_fn and check_interrupted_fn():
            raise InterruptedError()
        original_callback(msg)

    try:
        # --- Resume unhandled tool_calls from previous run ---
        early_exit = await _run_tool_calls(messages, tools_map, message_callback_with_interrupt_check)
        if early_exit:
            return early_exit

        for _ in range(max_iterations):
            raw = await provider.call_chat_completions_non_stream(
                messages, system_prompt, tools=openai_tools
            )

            tool_calls = raw.get("tool_calls")
            content = raw.get("content", "")
            provider_name = raw.get("provider")
            model = raw.get("model")

            assistant_msg_id = generate_message_id()
            parent_id = messages[-1].id if messages and messages[-1].id else None

            if not tool_calls:
                assistant_message = Message.from_dict({
                    "role": "assistant",
                    "content": content or "",
                    "timestamp": get_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": assistant_msg_id,
                    "parent_id": parent_id,
                    "provider": provider_name,
                    "model": model,
                })
                message_callback_with_interrupt_check(assistant_message)
                messages.append(assistant_message)
                return LoopResult("completed")

            # Has tool calls — check permissions and set statuses
            for tc_index, tc in enumerate(tool_calls):
                func = tc["function"]
                tool_name = func["name"]
                try:
                    tool_args = json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

                auto = auto_approve_fn() if auto_approve_fn else False
                if tools_map.get(tool_name) and not auto and not permission_manager.is_allowed(tool_name, tool_args):
                    for remaining_tc in tool_calls[tc_index:]:
                        remaining_tc["status"] = "pending"
                    break
                else:
                    tc["status"] = "approved"

            assistant_message = Message.from_dict({
                "role": "assistant",
                "content": content or "",
                "timestamp": get_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": assistant_msg_id,
                "parent_id": parent_id,
                "provider": provider_name,
                "model": model,
                "tool_calls": tool_calls,
            })
            message_callback_with_interrupt_check(assistant_message)
            messages.append(assistant_message)

            # Execute tool_calls (or exit if pending)
            early_exit = await _run_tool_calls(messages, tools_map, message_callback_with_interrupt_check)
            if early_exit:
                return early_exit
    except InterruptedError:
        return LoopResult("interrupted")
    except ClientError as e:
        error_message = Message.from_dict({
            "role": "assistant",
            "content": f"[agent] API client error (not retrying): {e}",
            "timestamp": get_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "parent_id": messages[-1].id if messages and messages[-1].id else None,
        })
        original_callback(error_message)
        messages.append(error_message)
        return LoopResult("error")
    except KeyboardInterrupt:
        print("\n[agent] Interrupted")
        return LoopResult("interrupted")
    except Exception as e:
        error_message = Message.from_dict({
            "role": "assistant",
            "content": f"[agent] Unexpected error: {e}",
            "timestamp": get_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "parent_id": messages[-1].id if messages and messages[-1].id else None,
        })
        original_callback(error_message)
        messages.append(error_message)
        return LoopResult("error")

    print("[agent] Max iterations reached")
    return LoopResult("max_iterations")
