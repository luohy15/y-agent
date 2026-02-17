"""Convert Claude Code stream-json messages to y-agent Message DTOs, and
run claude -p as a subprocess worker.

Claude Code `claude -p --output-format stream-json --verbose` emits one JSON
object per line with these types:
  - system  : init info (tools, model, session_id) — skipped
  - assistant: assistant message with content blocks (text, thinking, tool_use)
  - user    : tool results (tool_result content blocks)
  - result  : final summary — extracted for status

y-agent stores messages as:
  - role=assistant: content (text), reasoning_content (thinking), tool_calls list
  - role=tool: content (result string), tool name, arguments, tool_call_id
"""

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp


@dataclass
class ClaudeCodeResult:
    status: str  # "completed" | "interrupted" | "error"
    session_id: Optional[str] = None
    result_text: Optional[str] = None
    cost_usd: Optional[float] = None
    num_turns: Optional[int] = None


# ---------------------------------------------------------------------------
# Stream-json message converters
# ---------------------------------------------------------------------------

def _convert_assistant(obj: Dict, tool_use_index: Dict[str, Dict]) -> Message:
    """Convert a stream-json assistant object to a y-agent Message."""
    message = obj.get("message", {})
    content_blocks = message.get("content", [])
    model = message.get("model")
    uuid = obj.get("uuid")

    text_parts = []
    thinking_parts = []
    tool_calls = []

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        elif block_type == "tool_use":
            tool_id = block.get("id")
            tool_name = block.get("name")
            tool_input = block.get("input", {})
            tool_use_index[tool_id] = {"name": tool_name, "input": tool_input}
            tool_calls.append({
                "id": tool_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_input),
                },
                "status": "approved",
            })

    content = "\n".join(text_parts)
    reasoning = "\n".join(thinking_parts) if thinking_parts else None

    return Message.from_dict({
        "role": "assistant",
        "content": content,
        "reasoning_content": reasoning,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": uuid or generate_message_id(),
        "model": model,
        "provider": "claude-code",
        "tool_calls": tool_calls if tool_calls else None,
    })


def _convert_user_tool_results(obj: Dict, tool_use_index: Dict[str, Dict]) -> List[Message]:
    """Convert a stream-json user object (tool results) to y-agent tool Messages."""
    message = obj.get("message", {})
    content_blocks = message.get("content", [])

    messages = []
    for block in content_blocks:
        if block.get("type") != "tool_result":
            continue

        tool_call_id = block.get("tool_use_id")
        result_content = block.get("content", "")

        tool_info = tool_use_index.get(tool_call_id, {})
        tool_name = tool_info.get("name")
        tool_args = tool_info.get("input")

        msg = Message.from_dict({
            "role": "tool",
            "content": result_content if isinstance(result_content, str) else json.dumps(result_content),
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": obj.get("uuid") or generate_message_id(),
            "tool": tool_name,
            "arguments": tool_args,
            "tool_call_id": tool_call_id,
        })
        messages.append(msg)

    return messages


def parse_stream_line(line: str) -> Optional[Dict]:
    """Parse a single stream-json line into a dict. Returns None on parse failure."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Batch converters (for importing existing data)
# ---------------------------------------------------------------------------

def convert_stream_messages(stream_lines: List[str]) -> List[Message]:
    """Convert a list of stream-json lines into y-agent Messages."""
    messages: List[Message] = []
    tool_use_index: Dict[str, Dict] = {}

    for line in stream_lines:
        obj = parse_stream_line(line)
        if not obj:
            continue
        msg_type = obj.get("type")
        if msg_type == "assistant":
            messages.append(_convert_assistant(obj, tool_use_index))
        elif msg_type == "user":
            messages.extend(_convert_user_tool_results(obj, tool_use_index))

    for i in range(1, len(messages)):
        messages[i].parent_id = messages[i - 1].id
    return messages


def convert_jsonl_session(jsonl_lines: List[str]) -> List[Message]:
    """Convert Claude Code session JSONL lines into y-agent Messages."""
    messages: List[Message] = []
    tool_use_index: Dict[str, Dict] = {}

    for line in jsonl_lines:
        obj = parse_stream_line(line)
        if not obj:
            continue
        msg_type = obj.get("type")

        if msg_type == "assistant":
            messages.append(_convert_assistant(obj, tool_use_index))
        elif msg_type == "user":
            message = obj.get("message", {})
            content = message.get("content", "")

            if obj.get("isMeta"):
                continue
            if isinstance(content, str) and (
                content.startswith("<command-name>") or content.startswith("<local-command")
            ):
                continue

            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                messages.extend(_convert_user_tool_results(obj, tool_use_index))
            elif isinstance(content, str) and content.strip():
                messages.append(Message.from_dict({
                    "role": "user",
                    "content": content,
                    "timestamp": obj.get("timestamp", get_utc_iso8601_timestamp()),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": obj.get("uuid") or generate_message_id(),
                }))

    for i in range(1, len(messages)):
        messages[i].parent_id = messages[i - 1].id
    return messages


# ---------------------------------------------------------------------------
# Streaming converter (for real-time processing)
# ---------------------------------------------------------------------------

class StreamConverter:
    """Stateful line-by-line converter that links parent_ids across lines."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.tool_use_index: Dict[str, Dict] = {}
        self.last_message_id = last_message_id

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        msg_type = obj.get("type")
        messages: List[Message] = []

        if msg_type == "assistant":
            msg = _convert_assistant(obj, self.tool_use_index)
            msg.parent_id = self.last_message_id
            self.last_message_id = msg.id
            messages.append(msg)
        elif msg_type == "user":
            msgs = _convert_user_tool_results(obj, self.tool_use_index)
            for msg in msgs:
                msg.parent_id = self.last_message_id
                self.last_message_id = msg.id
            messages.extend(msgs)

        return messages


# ---------------------------------------------------------------------------
# Core subprocess runner
# ---------------------------------------------------------------------------

async def _run_claude_process(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    last_message_id: Optional[str],
    message_callback: Optional[Callable[[Message], None]],
    check_interrupted_fn: Optional[Callable[[], bool]],
) -> ClaudeCodeResult:
    """Spawn claude -p, stream output, convert messages, return result."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    converter = StreamConverter(last_message_id=last_message_id)
    result_data: Optional[Dict] = None
    session_id: Optional[str] = None

    try:
        if proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

        while proc.stdout:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace")

            if check_interrupted_fn and check_interrupted_fn():
                proc.send_signal(signal.SIGTERM)
                await proc.wait()
                return ClaudeCodeResult(status="interrupted", session_id=session_id)

            obj = parse_stream_line(line)
            if not obj:
                continue

            # Extract session_id from system init message
            if obj.get("type") == "system":
                session_id = obj.get("session_id")
                continue

            if obj.get("type") == "result":
                result_data = obj
                continue

            if message_callback:
                for msg in converter.process_line(line):
                    message_callback(msg)

    except Exception as e:
        logger.error("claude-code process exception: {}", e)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        stderr_bytes = await proc.stderr.read() if proc.stderr else b""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.error("claude-code stderr: {}", stderr_text)
        return ClaudeCodeResult(status="error", session_id=session_id)

    await proc.wait()

    # Read stderr for diagnostics
    stderr_bytes = await proc.stderr.read() if proc.stderr else b""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

    if result_data:
        status = "completed" if not result_data.get("is_error") else "error"
        if status == "error":
            logger.error("claude-code result error: result={} stderr={}", result_data.get("result"), stderr_text)
        return ClaudeCodeResult(
            status=status,
            session_id=result_data.get("session_id") or session_id,
            result_text=result_data.get("result"),
            cost_usd=result_data.get("total_cost_usd"),
            num_turns=result_data.get("num_turns"),
        )

    if proc.returncode != 0:
        logger.error("claude-code exited with code {} stderr={}", proc.returncode, stderr_text)
        return ClaudeCodeResult(status="error", session_id=session_id)

    return ClaudeCodeResult(status="completed", session_id=session_id)


# ---------------------------------------------------------------------------
# Public API — stateful session resume
# ---------------------------------------------------------------------------

async def run_claude_code(
    prompt: str,
    message_callback: Callable[[Message], None],
    cwd: Optional[str] = None,
    session_id: Optional[str] = None,
    resume: bool = False,
    last_message_id: Optional[str] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    model: Optional[str] = None,
    max_turns: Optional[int] = None,
    system_prompt: Optional[str] = None,
    allowed_tools: Optional[List[str]] = None,
) -> ClaudeCodeResult:
    """Run claude -p with optional session resume.

    First call: creates a new session, returns session_id in result.
    Subsequent calls: pass session_id + resume=True to continue the session.
    """
    if resume and session_id:
        # Resume existing session
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "-r", session_id,
            "--permission-mode", "bypassPermissions",
        ]
    else:
        # New session
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "bypassPermissions",
        ]

    if model:
        cmd.extend(["--model", model])
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    return await _run_claude_process(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        last_message_id=last_message_id,
        message_callback=message_callback,
        check_interrupted_fn=check_interrupted_fn,
    )
