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
import base64
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from storage.entity.dto import Message, VmConfig
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
            "provider": "claude-code",
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
# Core subprocess runner
# ---------------------------------------------------------------------------

async def _run_claude_process(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    last_message_id: Optional[str],
    message_callback: Optional[Callable[[Message], None]],
    check_interrupted_fn: Optional[Callable[[], bool]],
    env: Optional[Dict[str, str]] = None,
) -> ClaudeCodeResult:
    """Spawn claude -p, stream output, convert messages, return result."""
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
        limit=10 * 1024 * 1024,  # 10MB line limit for large JSON output
    )

    converter = StreamConverter(last_message_id=last_message_id)
    result_data: Optional[Dict] = None
    session_id: Optional[str] = None
    stderr_chunks: List[bytes] = []

    async def _drain_stderr():
        """Drain stderr concurrently to prevent pipe buffer deadlock."""
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

        await stderr_task

    except Exception as e:
        logger.error("claude-code process exception: {}", e)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.error("claude-code stderr: {}", stderr_text)
        error_detail = f"Claude Code process error: {e}"
        if stderr_text:
            error_detail += f"\n{stderr_text}"
        return ClaudeCodeResult(status="error", session_id=session_id, result_text=error_detail)

    await proc.wait()

    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()

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
        error_detail = f"Claude Code exited with code {proc.returncode}"
        if stderr_text:
            error_detail += f": {stderr_text}"
        return ClaudeCodeResult(status="error", session_id=session_id, result_text=error_detail)

    return ClaudeCodeResult(status="completed", session_id=session_id)


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


# ---------------------------------------------------------------------------
# Remote SSH runner
# ---------------------------------------------------------------------------

async def _run_claude_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    last_message_id: Optional[str],
    message_callback: Optional[Callable[[Message], None]],
    check_interrupted_fn: Optional[Callable[[], bool]],
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
) -> ClaudeCodeResult:
    """Run claude -p on a remote host via SSH (paramiko) with real-time stdout streaming."""
    import io
    import paramiko

    user, host, port = _parse_ssh_target(vm_config.vm_name)

    # Load private key from string
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    full_cmd = cmd + [prompt]

    # Build shell command string – wrap with exec so the shell PID *is* the
    # claude process PID, and echo the PID on the first line so we can kill
    # it on interrupt.
    inner_parts = ["date +%s > /tmp/ec2-ssh-last-seen;"]
    if env:
        for k, v in env.items():
            inner_parts.append(f"export {k}={_shell_quote(v)};")
    if cwd:
        inner_parts.append(f"cd {_shell_quote(cwd)} &&")
    inner_parts.append("exec " + " ".join(_shell_quote(c) for c in full_cmd))
    shell_cmd = "echo $$; " + " ".join(inner_parts)

    logger.info("ssh claude-code exec host={} port={} user={}", host, port, user)

    converter = StreamConverter(last_message_id=last_message_id)
    result_data: Optional[Dict] = None
    session_id: Optional[str] = None
    remote_pid: Optional[int] = None

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=user, pkey=key)

        stdin, stdout, stderr = client.exec_command(shell_cmd)
        stdin.close()

        channel = stdout.channel

        # Stream stdout line by line in a thread to avoid blocking the event loop
        def _read_lines():
            nonlocal result_data, session_id, remote_pid
            for raw_line in stdout:
                line = raw_line.strip()
                if not line:
                    continue

                # First line is the PID we echoed
                if remote_pid is None:
                    try:
                        remote_pid = int(line)
                        continue
                    except ValueError:
                        pass

                if check_interrupted_fn and check_interrupted_fn():
                    logger.info("ssh claude-code interrupted, killing remote pid={}", remote_pid)
                    # Kill the remote process tree before closing
                    if remote_pid is not None:
                        try:
                            client.exec_command(f"kill -9 -{remote_pid} 2>/dev/null; kill -9 {remote_pid} 2>/dev/null")
                        except Exception:
                            pass
                    channel.close()
                    return "interrupted"

                obj = parse_stream_line(line)
                if not obj:
                    continue

                if obj.get("type") == "system":
                    session_id = obj.get("session_id")
                    continue
                if obj.get("type") == "result":
                    result_data = obj
                    continue

                if message_callback:
                    for msg in converter.process_line(line):
                        message_callback(msg)
            return None

        loop = asyncio.get_event_loop()
        interrupted = await loop.run_in_executor(None, _read_lines)

        if interrupted == "interrupted":
            client.close()
            return ClaudeCodeResult(status="interrupted", session_id=session_id)

        stderr_text = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        logger.info("ssh claude-code done exit_code={}", exit_code)
        client.close()

    except Exception as e:
        logger.error("ssh claude-code error: {} {}", type(e).__name__, e)
        return ClaudeCodeResult(status="error", session_id=session_id)

    if result_data:
        status = "completed" if not result_data.get("is_error") else "error"
        if status == "error":
            logger.error("ssh claude-code result error: result={} stderr={}", result_data.get("result"), stderr_text)
        return ClaudeCodeResult(
            status=status,
            session_id=result_data.get("session_id") or session_id,
            result_text=result_data.get("result"),
            cost_usd=result_data.get("total_cost_usd"),
            num_turns=result_data.get("num_turns"),
        )

    if exit_code != 0:
        logger.error("ssh claude-code exited with code {} stderr={}", exit_code, stderr_text)
        error_detail = f"Claude Code (SSH) exited with code {exit_code}"
        if stderr_text:
            error_detail += f": {stderr_text}"
        return ClaudeCodeResult(status="error", session_id=session_id, result_text=error_detail)

    return ClaudeCodeResult(status="completed", session_id=session_id)


def _shell_quote(s: str) -> str:
    """Shell-quote a string for safe use in a remote command."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# Image materialization helpers
# ---------------------------------------------------------------------------

def _decode_data_url(data_url: str) -> tuple:
    """Decode a data URL into (bytes, extension). Returns (None, None) on failure."""
    try:
        # data:image/jpeg;base64,/9j/4AAQ...
        header, b64_data = data_url.split(",", 1)
        mime = header.split(":")[1].split(";")[0]  # e.g. image/jpeg
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "jpg")
        return base64.b64decode(b64_data), ext
    except Exception:
        return None, None


def _materialize_images_local(images: List[str], cwd: str) -> List[str]:
    """Decode base64 data URLs and write to local files. Returns list of file paths."""
    img_dir = os.path.join(cwd, ".y-agent-images")
    os.makedirs(img_dir, exist_ok=True)

    paths = []
    for data_url in images:
        img_bytes, ext = _decode_data_url(data_url)
        if img_bytes is None:
            continue
        filename = f"img_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(img_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        paths.append(filepath)
        logger.info("Materialized image: {} ({} bytes)", filepath, len(img_bytes))

    return paths


def _materialize_images_ssh(images: List[str], cwd: str, vm_config: "VmConfig") -> List[str]:
    """Upload base64 data URLs to remote host via SFTP. Returns list of remote file paths."""
    import io
    import paramiko

    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    paths = []
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=user, pkey=key)

        sftp = client.open_sftp()
        img_dir = f"{cwd}/.y-agent-images"
        try:
            sftp.mkdir(img_dir)
        except IOError:
            pass  # directory already exists

        for data_url in images:
            img_bytes, ext = _decode_data_url(data_url)
            if img_bytes is None:
                continue
            filename = f"img_{uuid.uuid4().hex[:8]}.{ext}"
            filepath = f"{img_dir}/{filename}"
            with sftp.open(filepath, "wb") as f:
                f.write(img_bytes)
            paths.append(filepath)
            logger.info("SFTP uploaded image: {} ({} bytes)", filepath, len(img_bytes))

        sftp.close()
        client.close()
    except Exception as e:
        logger.error("SFTP image upload failed: {} {}", type(e).__name__, e)

    return paths


def _prepend_image_paths(prompt: str, image_paths: List[str]) -> str:
    """Prepend image file paths to the prompt text."""
    if not image_paths:
        return prompt
    lines = [f"[Attached image: {p}]" for p in image_paths]
    return "\n".join(lines) + "\n\n" + prompt


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
    vm_config: Optional[VmConfig] = None,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    images: Optional[List[str]] = None,
    chat_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    skill: Optional[str] = None,
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

    # Build env vars for API configuration and context
    env: Optional[Dict[str, str]] = None
    if api_base_url or api_key or chat_id or trace_id or skill:
        env = {}
        if api_base_url:
            env["ANTHROPIC_BASE_URL"] = api_base_url
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if chat_id:
            env["Y_CHAT_ID"] = chat_id
        if trace_id:
            env["Y_TRACE_ID"] = trace_id
        if skill:
            env["Y_SKILL"] = skill

    # Materialize images as files and prepend paths to prompt
    effective_cwd = cwd or (vm_config.work_dir if vm_config else None) or os.getcwd()
    if images:
        is_ssh = vm_config and vm_config.vm_name and vm_config.vm_name.startswith("ssh:")
        if is_ssh:
            image_paths = _materialize_images_ssh(images, effective_cwd, vm_config)
        else:
            image_paths = _materialize_images_local(images, effective_cwd)
        prompt = _prepend_image_paths(prompt, image_paths)

    if vm_config and vm_config.vm_name and vm_config.vm_name.startswith("ssh:"):
        return await _run_claude_ssh(
            cmd=cmd,
            prompt=prompt,
            cwd=cwd or (vm_config.work_dir if vm_config else None),
            last_message_id=last_message_id,
            message_callback=message_callback,
            check_interrupted_fn=check_interrupted_fn,
            vm_config=vm_config,
            env=env,
        )

    return await _run_claude_process(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        last_message_id=last_message_id,
        message_callback=message_callback,
        check_interrupted_fn=check_interrupted_fn,
        env=env,
    )
