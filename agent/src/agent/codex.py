"""Run OpenAI Codex CLI (`codex exec`) as a subprocess worker.

Codex `codex exec --json --dangerously-bypass-approvals-and-sandbox` emits JSONL events:
  - thread.started  : thread_id
  - turn.started    : new turn begins
  - item.started    : tool/message item begins (command_execution, file_change, agent_message, etc.)
  - item.completed  : tool/message item finishes
  - turn.completed  : usage stats
  - turn.failed     : error in turn
  - error           : top-level error

Maps these events to y-agent Message DTOs using the same format as claude_code.py.
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import parse_stream_line, _parse_ssh_target, _shell_quote, _start_interrupt_watchdog, _stop_interrupt_watchdog

_SHELL_WRAPPER_RE = re.compile(
    r'^(/\S+/(?:bash|zsh|sh|fish|dash))\s+-\w*c\s+(.+)$',
    re.DOTALL,
)


def _strip_shell_wrapper(command: str) -> str:
    """Strip shell wrapper (e.g. '/usr/bin/zsh -lc pwd') to extract the actual command."""
    m = _SHELL_WRAPPER_RE.match(command)
    if m:
        inner = m.group(2)
        if (inner.startswith("'") and inner.endswith("'")) or \
           (inner.startswith('"') and inner.endswith('"')):
            inner = inner[1:-1]
        return inner
    return command


@dataclass
class CodexResult:
    status: str  # "completed" | "interrupted" | "error"
    thread_id: Optional[str] = None
    result_text: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class CodexStreamConverter:
    """Stateful JSONL event converter that maps Codex events to y-agent Messages."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.thread_id: Optional[str] = None
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.num_turns: int = 0
        self._pending_items: Dict[str, str] = {}  # codex item_id -> tool_call_id

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        return msg

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        event_type = obj.get("type")
        messages: List[Message] = []

        if event_type == "thread.started":
            self.thread_id = obj.get("thread_id")

        elif event_type == "item.started":
            item = obj.get("item", {})
            item_type = item.get("type")
            item_id = item.get("id") or generate_message_id()

            if item_type == "command_execution":
                command = _strip_shell_wrapper(item.get("command", ""))
                self._pending_items[item_id] = item_id
                msg = Message.from_dict({
                    "role": "assistant",
                    "content": "",
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "provider": "codex",
                    "tool_calls": [{
                        "id": item_id,
                        "type": "function",
                        "function": {
                            "name": "Bash",
                            "arguments": json.dumps({"command": command}),
                        },
                        "status": "approved",
                    }],
                })
                messages.append(self._emit(msg))

            elif item_type == "file_change":
                file_path = item.get("file_path", "")
                self._pending_items[item_id] = item_id
                msg = Message.from_dict({
                    "role": "assistant",
                    "content": "",
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "provider": "codex",
                    "tool_calls": [{
                        "id": item_id,
                        "type": "function",
                        "function": {
                            "name": "Edit",
                            "arguments": json.dumps({"file_path": file_path}),
                        },
                        "status": "approved",
                    }],
                })
                messages.append(self._emit(msg))

        elif event_type == "item.completed":
            item = obj.get("item", {})
            item_type = item.get("type")
            item_id = item.get("id")
            tool_call_id = self._pending_items.pop(item_id, None) if item_id else None
            if not tool_call_id:
                tool_call_id = item_id or generate_message_id()

            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    msg = Message.from_dict({
                        "role": "assistant",
                        "content": text,
                        "timestamp": get_utc_iso8601_timestamp(),
                        "unix_timestamp": get_unix_timestamp(),
                        "id": generate_message_id(),
                        "provider": "codex",
                    })
                    messages.append(self._emit(msg))

            elif item_type == "command_execution":
                output = item.get("output", "")
                command = _strip_shell_wrapper(item.get("command", ""))
                msg = Message.from_dict({
                    "role": "tool",
                    "content": output if isinstance(output, str) else json.dumps(output),
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "tool": "Bash",
                    "arguments": {"command": command},
                    "tool_call_id": tool_call_id,
                })
                messages.append(self._emit(msg))

            elif item_type == "file_change":
                diff = item.get("diff", "") or item.get("content", "") or "file changed"
                file_path = item.get("file_path", "")
                msg = Message.from_dict({
                    "role": "tool",
                    "content": diff if isinstance(diff, str) else json.dumps(diff),
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "tool": "Edit",
                    "arguments": {"file_path": file_path},
                    "tool_call_id": tool_call_id,
                })
                messages.append(self._emit(msg))

            else:
                # Other completed items (reasoning, mcp_tool_call, web_search, plan_update)
                text = item.get("text", "")
                if text:
                    msg = Message.from_dict({
                        "role": "assistant",
                        "content": text,
                        "timestamp": get_utc_iso8601_timestamp(),
                        "unix_timestamp": get_unix_timestamp(),
                        "id": generate_message_id(),
                        "provider": "codex",
                    })
                    messages.append(self._emit(msg))

        elif event_type == "turn.completed":
            usage = obj.get("usage", {})
            self.total_input_tokens += usage.get("input_tokens", 0)
            self.total_output_tokens += usage.get("output_tokens", 0)
            self.num_turns += 1

        elif event_type == "turn.failed":
            error = obj.get("error", {})
            error_msg = error.get("message", "Turn failed")
            logger.error("codex turn.failed: {}", error_msg)

        elif event_type == "error":
            error_msg = obj.get("message", "Unknown error")
            logger.error("codex error event: {}", error_msg)

        return messages


# ---------------------------------------------------------------------------
# Local subprocess runner
# ---------------------------------------------------------------------------

async def _run_codex_process(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    last_message_id: Optional[str],
    message_callback: Optional[Callable[[Message], None]],
    check_interrupted_fn: Optional[Callable[[], bool]],
    env: Optional[Dict[str, str]] = None,
) -> CodexResult:
    """Spawn codex exec, stream output, convert messages, return result."""
    proc_env = dict(os.environ)
    if env:
        proc_env.update(env)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=proc_env,
        limit=10 * 1024 * 1024,
    )

    converter = CodexStreamConverter(last_message_id=last_message_id)
    stderr_chunks: List[bytes] = []
    last_error_msg: Optional[str] = None

    async def _drain_stderr():
        while proc.stderr:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk)

    try:
        if proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

        stderr_task = asyncio.create_task(_drain_stderr())

        while proc.stdout:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace")

            if check_interrupted_fn and check_interrupted_fn():
                proc.kill()
                await proc.wait()
                stderr_task.cancel()
                return CodexResult(status="interrupted", thread_id=converter.thread_id)

            # Track error events for final status
            obj = parse_stream_line(line)
            if obj:
                if obj.get("type") == "error":
                    last_error_msg = obj.get("message", "Unknown error")
                elif obj.get("type") == "turn.failed":
                    err = obj.get("error", {})
                    last_error_msg = err.get("message", "Turn failed")

            if message_callback:
                for msg in converter.process_line(line):
                    message_callback(msg)

        await stderr_task

    except Exception as e:
        logger.error("codex process exception: {}", e)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.error("codex stderr: {}", stderr_text)
        error_detail = f"Codex process error: {e}"
        if stderr_text:
            error_detail += f"\n{stderr_text}"
        return CodexResult(status="error", thread_id=converter.thread_id, result_text=error_detail)

    await proc.wait()

    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        logger.error("codex exited with code {} stderr={}", proc.returncode, stderr_text)
        error_detail = last_error_msg or f"Codex exited with code {proc.returncode}"
        if stderr_text and not last_error_msg:
            error_detail += f": {stderr_text}"
        return CodexResult(
            status="error",
            thread_id=converter.thread_id,
            result_text=error_detail,
            input_tokens=converter.total_input_tokens or None,
            output_tokens=converter.total_output_tokens or None,
        )

    return CodexResult(
        status="completed",
        thread_id=converter.thread_id,
        input_tokens=converter.total_input_tokens or None,
        output_tokens=converter.total_output_tokens or None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_codex(
    prompt: str,
    message_callback: Callable[[Message], None],
    cwd: Optional[str] = None,
    last_message_id: Optional[str] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> CodexResult:
    """Run codex exec as a subprocess, stream JSONL output, return result.

    If thread_id is provided, resumes an existing session via `codex exec resume`.
    """
    if thread_id:
        # resume subcommand doesn't support -C; pass cwd to subprocess instead
        cmd = ["codex", "exec", "resume", thread_id, "--json", "--dangerously-bypass-approvals-and-sandbox"]
    else:
        cmd = ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox"]
        if cwd:
            cmd.extend(["-C", cwd])
    if model:
        cmd.extend(["-m", model])

    env: Optional[Dict[str, str]] = None
    if api_key:
        env = {"OPENAI_API_KEY": api_key}

    return await _run_codex_process(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        last_message_id=last_message_id,
        message_callback=message_callback,
        check_interrupted_fn=check_interrupted_fn,
        env=env,
    )


# ---------------------------------------------------------------------------
# Detach mode: tail SSH output
# ---------------------------------------------------------------------------

async def tail_codex_output(
    chat_id: str,
    vm_config: "VmConfig",
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    ssh_client=None,
) -> dict:
    """Tail a detached codex process's stdout file via SSH.

    Structurally identical to tail_ssh_output() in claude_code.py but uses
    CodexStreamConverter and extracts usage from turn.completed events.

    Returns dict with:
      - offset: new line offset
      - last_message_id: last processed message id
      - thread_id: codex thread id (if found)
      - is_done: True if process exited
      - result_data: turn.completed usage data (if available)
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
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = CodexStreamConverter(last_message_id=last_message_id)
    result_data = None
    last_error_data = None
    current_offset = offset

    try:
        tail_cmd = (
            f"tail -n +{offset + 1} -f {_shell_quote(stdout_file)} & TAIL_PID=$!; "
            f"(while ! test -f {_shell_quote(exit_file)}; do sleep 2; done; "
            f"sleep 1; kill $TAIL_PID 2>/dev/null) & "
            f"wait $TAIL_PID 2>/dev/null"
        )

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            logger.info("interrupt watchdog (codex detached): killing tmux session cc-{}", chat_id)
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

        wd_event, wd_thread = _start_interrupt_watchdog(check_interrupted_fn, _kill_detached)

        def _read_lines():
            nonlocal result_data, last_error_data, current_offset
            try:
                for raw_line in stdout_ch:
                    line = raw_line.strip()
                    if not line:
                        continue

                    current_offset += 1

                    if check_interrupted_fn and check_interrupted_fn():
                        try:
                            client.exec_command(
                                f"tmux kill-session -t {_shell_quote(f'cc-{chat_id}')} 2>/dev/null"
                            )
                            client.exec_command(f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.stdout /tmp/cc-{chat_id}.stderr /tmp/cc-{chat_id}.exit 2>/dev/null")
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "interrupted"

                    if check_deadline_fn and check_deadline_fn():
                        try:
                            client.exec_command(f"pkill -f 'tail.*cc-{chat_id}.stdout' 2>/dev/null")
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    evt = obj.get("type")

                    # Track turn.completed for usage (last one wins)
                    if evt == "turn.completed":
                        result_data = obj
                        # Still process through converter for token tracking
                        converter.process_line(line)
                        continue

                    # Track errors
                    if evt == "turn.failed":
                        last_error_data = {"is_error": True, "result": obj.get("error", {}).get("message")}
                        converter.process_line(line)
                        continue
                    if evt == "error":
                        last_error_data = {"is_error": True, "result": obj.get("message")}
                        converter.process_line(line)
                        continue

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

            return None

        loop = asyncio.get_event_loop()
        exit_reason = await loop.run_in_executor(None, _read_lines)

        _stop_interrupt_watchdog(wd_event, wd_thread)

        if owns_client:
            client.close()

        if exit_reason == "interrupted":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "thread_id": converter.thread_id,
                "is_done": True,
                "result_data": None,
                "status": "interrupted",
            }

        if exit_reason == "deadline":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "thread_id": converter.thread_id,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
            }

        # Process finished normally
        status = "completed"
        if last_error_data:
            status = "error"
            result_data = last_error_data

        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "thread_id": converter.thread_id,
            "is_done": True,
            "result_data": result_data,
            "status": status,
        }

    except Exception as e:
        logger.error("tail_codex_output error: {} {}", type(e).__name__, e)
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id if converter else last_message_id,
            "thread_id": converter.thread_id if converter else None,
            "is_done": False,
            "result_data": None,
            "status": "error",
        }
