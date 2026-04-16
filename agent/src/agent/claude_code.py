"""Convert Claude Code stream-json messages to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

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
import re
import socket
import time
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from storage.entity.dto import Message, VmConfig
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.poll_loop import PollLoop


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
        "provider": "claude_code",
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



def convert_history_session(jsonl_lines: List[str]) -> Tuple[List[Message], Optional[str], Optional[str]]:
    """Convert Claude Code history JSONL (from ~/.claude/projects/) into y-agent Messages.

    History JSONL differs from stream-json: each line has exactly ONE content block,
    so consecutive assistant lines must be merged into a single Message.

    Returns (messages, session_id, work_dir).
    """
    messages: List[Message] = []
    tool_use_index: Dict[str, Dict] = {}
    session_id: Optional[str] = None
    work_dir: Optional[str] = None

    # Accumulator for merging consecutive assistant lines
    pending_assistant_blocks: List[Dict] = []
    pending_assistant_model: Optional[str] = None
    pending_assistant_uuid: Optional[str] = None
    pending_assistant_ts: Optional[str] = None

    def _flush_assistant():
        """Flush accumulated assistant blocks into a single Message."""
        nonlocal pending_assistant_blocks, pending_assistant_model, pending_assistant_uuid, pending_assistant_ts
        if not pending_assistant_blocks:
            return

        text_parts = []
        thinking_parts = []
        tool_calls = []

        for block in pending_assistant_blocks:
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
        ts = pending_assistant_ts or get_utc_iso8601_timestamp()

        messages.append(Message.from_dict({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning,
            "timestamp": ts,
            "unix_timestamp": _iso_to_unix_ms(ts),
            "id": pending_assistant_uuid or generate_message_id(),
            "model": pending_assistant_model,
            "provider": "claude_code",
            "tool_calls": tool_calls if tool_calls else None,
        }))

        pending_assistant_blocks = []
        pending_assistant_model = None
        pending_assistant_uuid = None
        pending_assistant_ts = None

    for line in jsonl_lines:
        obj = parse_stream_line(line)
        if not obj:
            continue

        msg_type = obj.get("type")

        # Skip non-message types
        if msg_type in ("file-history-snapshot", "progress", "system"):
            continue
        if obj.get("isMeta") or obj.get("isSidechain"):
            continue

        # Extract metadata from first real line
        if session_id is None:
            session_id = obj.get("sessionId")
        if work_dir is None:
            work_dir = obj.get("cwd")

        if msg_type == "assistant":
            message = obj.get("message", {})
            content_blocks = message.get("content", [])
            # Set model/uuid/ts from first assistant line in a group
            if not pending_assistant_blocks:
                pending_assistant_model = message.get("model")
                pending_assistant_uuid = obj.get("uuid")
                pending_assistant_ts = obj.get("timestamp")
            pending_assistant_blocks.extend(content_blocks)

        elif msg_type == "user":
            # Flush any pending assistant before processing user
            _flush_assistant()

            message = obj.get("message", {})
            content = message.get("content", "")
            ts = obj.get("timestamp", get_utc_iso8601_timestamp())

            # Skip command/system user messages
            if isinstance(content, str) and (
                content.startswith("<command-name>") or content.startswith("<command-message>")
                or content.startswith("<local-command")
            ):
                continue

            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                tool_msgs = _convert_user_tool_results(obj, tool_use_index)
                # Override timestamps from JSONL (the helper uses current time)
                unix_ts = _iso_to_unix_ms(ts)
                for tm in tool_msgs:
                    tm.timestamp = ts
                    tm.unix_timestamp = unix_ts
                messages.extend(tool_msgs)
            elif isinstance(content, str) and content.strip():
                # Strip system-injected XML tags
                cleaned = _strip_system_xml(content)
                if cleaned.strip():
                    messages.append(Message.from_dict({
                        "role": "user",
                        "content": cleaned,
                        "timestamp": ts,
                        "unix_timestamp": _iso_to_unix_ms(ts),
                        "id": obj.get("uuid") or generate_message_id(),
                    }))

    # Flush any trailing assistant blocks
    _flush_assistant()

    # Link parent_ids
    for i in range(1, len(messages)):
        messages[i].parent_id = messages[i - 1].id

    return messages, session_id, work_dir


def _iso_to_unix_ms(iso_str: str) -> int:
    """Convert ISO 8601 timestamp to unix milliseconds."""
    from datetime import datetime, timezone
    try:
        # Handle 'Z' suffix
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return get_unix_timestamp()


# Regex to strip system-injected XML blocks from user content
_SYSTEM_XML_RE = re.compile(
    r"<(?:system-reminder|context|environment_details|search_results|"
    r"relevant_files|claude-md|fast_mode_info|currentDate)[^>]*>[\s\S]*?"
    r"</(?:system-reminder|context|environment_details|search_results|"
    r"relevant_files|claude-md|fast_mode_info|currentDate)>",
    re.DOTALL,
)


def _strip_system_xml(content: str) -> str:
    """Remove system-injected XML blocks from user message content."""
    return _SYSTEM_XML_RE.sub("", content).strip()


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
# SSH helper
# ---------------------------------------------------------------------------

def _parse_ssh_target(vm_name: str) -> tuple:
    """Parse 'ssh:user@host:port' or 'ssh:host' into (user, host, port)."""
    raw = vm_name[len("ssh:"):]
    user = None
    port = 22
    if "@" in raw:
        user, raw = raw.split("@", 1)
    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = raw
    return user, host, port


def _shell_quote(s: str) -> str:
    """Shell-quote a string for safe use in a remote command."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _ssh_exec(client, cmd: str) -> str:
    """Execute a command via SSH and return stdout. Raises on non-zero exit."""
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace")
    if exit_code != 0:
        err = stderr.read().decode("utf-8", errors="replace")
        if "no server running" not in err and "session not found" not in err:
            raise RuntimeError(f"SSH command failed (exit {exit_code}): {err}")
    return output


# ---------------------------------------------------------------------------
# Detached SSH runner (tmux-based, for Lambda timeout resilience)
# ---------------------------------------------------------------------------

async def start_detached_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
    ssh_client=None,
) -> Optional[str]:
    """Start claude -p in a detached tmux session on remote host.

    If ssh_client is provided, reuses that connection (from a pool).
    Otherwise creates and closes its own connection.

    Prompt is written via SFTP to a stdin file.
    stdout/stderr redirected to /tmp/cc-{chat_id}.* files.

    Returns session_id if found in initial output, else None.
    """
    owns_client = ssh_client is None
    if owns_client:
        import io
        import paramiko

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(host, port=port, username=user, pkey=key)

    client = ssh_client

    try:
        # 1. Clean up any stale files/session (before writing stdin)
        _ssh_exec(client, f"tmux kill-session -t {_shell_quote(f'cc-{chat_id}')} 2>/dev/null; "
                         f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.stdout /tmp/cc-{chat_id}.stderr /tmp/cc-{chat_id}.exit 2>/dev/null")

        # 2. Write prompt to stdin file via SFTP in stream-json format
        stdin_file = f"/tmp/cc-{chat_id}.stdin"
        payload = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            },
        }) + "\n"
        sftp = client.open_sftp()
        with sftp.open(stdin_file, "w") as f:
            f.write(payload)
        sftp.close()

        # 3. Build the claude command (with stream-json input via tail -f pipe)
        full_cmd = cmd + ["--input-format", "stream-json"]
        inner_parts = ["date +%s > /tmp/ec2-ssh-last-seen;"]
        if env:
            for k, v in env.items():
                inner_parts.append(f"export {k}={_shell_quote(v)};")
        if cwd:
            inner_parts.append(f"cd {_shell_quote(cwd)} &&")

        claude_cmd = " ".join(_shell_quote(c) for c in full_cmd)
        stdout_file = f"/tmp/cc-{chat_id}.stdout"
        stderr_file = f"/tmp/cc-{chat_id}.stderr"
        exit_file = f"/tmp/cc-{chat_id}.exit"

        inner_parts.append(
            f"tail -f -n +1 {_shell_quote(stdin_file)} | {claude_cmd} "
            f"> {_shell_quote(stdout_file)} "
            f"2> {_shell_quote(stderr_file)}; "
            f"echo $? > {_shell_quote(exit_file)}"
        )

        tmux_cmd = (
            f"tmux new-session -d -s {_shell_quote(f'cc-{chat_id}')} "
            f"{_shell_quote(' '.join(inner_parts))}"
        )

        # 4. Start tmux session
        _ssh_exec(client, tmux_cmd)

        # 5. Wait briefly for stdout file to appear and check for session_id
        await asyncio.sleep(2)

        session_id = None
        try:
            output = _ssh_exec(client, f"head -5 {_shell_quote(stdout_file)} 2>/dev/null")
            for line in output.strip().split("\n"):
                obj = parse_stream_line(line)
                if obj and obj.get("type") == "system":
                    session_id = obj.get("session_id")
                    break
        except Exception:
            pass

        return session_id
    finally:
        if owns_client:
            client.close()


async def tail_ssh_output(
    chat_id: str,
    vm_config: "VmConfig",
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    ssh_client=None,
    check_steer_fn: Optional[Callable[[], List[Tuple[str, str]]]] = None,
) -> dict:
    """Tail a detached claude-code process's stdout file via SSH.

    If ssh_client is provided, reuses that connection (from a pool).
    Otherwise creates and closes its own connection.

    Returns dict with:
      - offset: new line offset
      - last_message_id: last processed message id
      - session_id: claude code session id (if found)
      - is_done: True if process exited
      - result_data: the "result" stream-json object (if process completed)
      - status: "completed" | "error" | "interrupted" | "monitoring"
    """
    owns_client = ssh_client is None
    if owns_client:
        import io
        import paramiko

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(host, port=port, username=user, pkey=key)

    client = ssh_client
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = StreamConverter(last_message_id=last_message_id)
    result_data = None
    session_id = None
    current_offset = offset
    consumed_steer_ids = []

    try:
        # tail from offset, follow until exit file appears or deadline/interrupt
        tail_cmd = (
            f"tail -n +{offset + 1} -f {_shell_quote(stdout_file)} & TAIL_PID=$!; "
            f"(while ! test -f {_shell_quote(exit_file)}; do sleep 2; done; "
            f"sleep 1; kill $TAIL_PID 2>/dev/null) & "
            f"wait $TAIL_PID 2>/dev/null"
        )

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            logger.info("interrupt watchdog (detached): killing tmux session cc-{}", chat_id)
            try:
                client.exec_command(
                    f"tmux kill-session -t {_shell_quote(f'cc-{chat_id}')} 2>/dev/null"
                )
                client.exec_command(f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.stdout /tmp/cc-{chat_id}.stderr /tmp/cc-{chat_id}.exit 2>/dev/null")
            except Exception:
                pass
            try:
                stdout_ch.channel.close()
            except Exception:
                pass

        def _on_steer_detached(text, msg_id):
            payload = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                },
            })
            client.exec_command(
                f"printf '%s\\n' {_shell_quote(payload)} >> {_shell_quote(stdin_file)}"
            )
            converter.last_message_id = msg_id
            consumed_steer_ids.append(msg_id)

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer_detached,
        )
        poll.start()

        def _readline_with_timeout(channel, timeout=1.0):
            """Yield lines from paramiko channel with timeout. Yields None on timeout."""
            buf = b""
            channel.channel.settimeout(timeout)
            while True:
                try:
                    chunk = channel.channel.recv(4096)
                    if not chunk:
                        # Channel closed / EOF
                        if buf:
                            yield buf.decode("utf-8", errors="replace")
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        yield line.decode("utf-8", errors="replace")
                except socket.timeout:
                    yield None  # timeout, no data

        def _kill_tmux():
            try:
                client.exec_command(
                    f"tmux kill-session -t {_shell_quote(f'cc-{chat_id}')} 2>/dev/null"
                )
                client.exec_command(f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.stdout /tmp/cc-{chat_id}.stderr /tmp/cc-{chat_id}.exit 2>/dev/null")
            except Exception:
                pass
            try:
                stdout_ch.channel.close()
            except Exception:
                pass

        def _read_lines():
            nonlocal result_data, session_id, current_offset
            result_deadline = None
            try:
                for raw_line in _readline_with_timeout(stdout_ch, timeout=1.0):
                    # Check interrupt/deadline on every iteration (including timeouts)
                    if check_interrupted_fn and check_interrupted_fn():
                        _kill_tmux()
                        return "interrupted"

                    if check_deadline_fn and check_deadline_fn():
                        try:
                            client.exec_command(f"pkill -f 'tail.*cc-{chat_id}.stdout' 2>/dev/null")
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    if raw_line is None:
                        # Timeout — check if result deadline expired
                        if result_deadline and time.monotonic() > result_deadline:
                            _kill_tmux()
                            return None  # natural completion
                        continue

                    line = raw_line.strip()
                    if not line:
                        continue

                    current_offset += 1

                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    if obj.get("type") == "system":
                        session_id = obj.get("session_id")
                        if result_deadline:
                            # New turn started from steer — reset deadline
                            result_deadline = None
                        continue
                    if obj.get("type") == "result":
                        result_data = obj
                        # Don't kill immediately — wait for potential steer
                        result_deadline = time.monotonic() + 10
                        continue

                    if obj.get("type") in ("assistant",) and result_deadline:
                        # New turn started from steer — reset deadline
                        result_deadline = None

                    if message_callback:
                        for msg in converter.process_line(line):
                            message_callback(msg)
            except (OSError, EOFError, Exception) as e:
                if check_interrupted_fn and check_interrupted_fn():
                    return "interrupted"
                if not isinstance(e, (OSError, EOFError)):
                    raise

            if check_interrupted_fn and check_interrupted_fn():
                return "interrupted"

            # If we exited the loop with a pending result (channel closed), still complete
            return None

        loop = asyncio.get_event_loop()
        exit_reason = await loop.run_in_executor(None, _read_lines)

        poll.stop()

        if owns_client:
            client.close()

        if exit_reason == "interrupted":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": session_id,
                "is_done": True,
                "result_data": None,
                "status": "interrupted",
                "consumed_steer_ids": consumed_steer_ids,
            }

        if exit_reason == "deadline":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": session_id,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
                "consumed_steer_ids": consumed_steer_ids,
            }

        # Process finished normally
        status = "completed"
        if result_data and result_data.get("is_error"):
            status = "error"

        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "session_id": result_data.get("session_id") or session_id if result_data else session_id,
            "is_done": True,
            "result_data": result_data,
            "status": status,
            "consumed_steer_ids": consumed_steer_ids,
        }

    except Exception as e:
        logger.error("tail_ssh_output error: {} {}", type(e).__name__, e)
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id if converter else last_message_id,
            "session_id": session_id,
            "is_done": False,
            "result_data": None,
            "status": "error",
            "consumed_steer_ids": consumed_steer_ids,
        }
