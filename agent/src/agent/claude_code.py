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
import base64
import json
import mimetypes
import re
import threading
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from storage.entity.dto import Message, VmConfig
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.poll_loop import PollLoop


# ---------------------------------------------------------------------------
# Stream-json message converters
# ---------------------------------------------------------------------------

def _convert_assistant(obj: Dict, tool_use_index: Dict[str, Dict]) -> Optional[Message]:
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

    if not content and not reasoning and not tool_calls:
        return None

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
            msg = _convert_assistant(obj, tool_use_index)
            if msg:
                messages.append(msg)
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

        if not content and not reasoning and not tool_calls:
            pending_assistant_blocks = []
            pending_assistant_model = None
            pending_assistant_uuid = None
            pending_assistant_ts = None
            return

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
            if not msg:
                return []
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


def _claude_resume_session_id(cmd: List[str]) -> Optional[str]:
    """Return the Claude Code resume session id from `-r <id>`, if present."""
    try:
        resume_index = cmd.index("-r")
    except ValueError:
        return None
    if resume_index + 1 >= len(cmd):
        return None
    return cmd[resume_index + 1]


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


def _stream_error_suffix(stream_error: Optional[Exception]) -> str:
    """Format a swallowed tail stream error for inclusion in a no-result error
    message, so a transient SSH channel failure is distinguishable from a
    clean process exit."""
    if stream_error is None:
        return ""
    return f" (tail stream error: {type(stream_error).__name__}: {stream_error})"


def _no_result_error_message(client, chat_id: str, backend: str, stream_error: Optional[Exception] = None) -> str:
    """Build a precise error message for a tmux session that ended without ever
    emitting a final result event.

    The detach launcher writes the subprocess exit code to
    `/tmp/cc-<chat_id>.exit` (`echo $EC > exit_file`). That code tells us *why*
    the process is gone — e.g. a SIGTERM/SIGKILL from an external reaper or the
    OOM killer (a common false alarm previously mis-reported as a resume
    failure) vs. a genuine startup/resume error. Fall back to a generic message
    when the exit file is missing, empty, or unparseable.
    """
    suffix = _stream_error_suffix(stream_error)
    generic = (
        f"{backend} exited before producing output — likely a session resume "
        f"failure or startup error.{suffix}"
    )
    exit_file = f"/tmp/cc-{chat_id}.exit"
    try:
        raw = _ssh_exec(client, f"cat {_shell_quote(exit_file)} 2>/dev/null").strip()
    except Exception as e:
        return (
            f"{backend} exited before producing output: exit status unreadable "
            f"(ssh error: {type(e).__name__}: {e}).{suffix}"
        )
    if not raw:
        return generic
    try:
        code = int(raw)
    except ValueError:
        return generic

    if code == 143:
        return (
            f"{backend} exited before producing output: terminated by SIGTERM "
            f"(15) — likely killed by an external reaper/OOM, not a resume failure.{suffix}"
        )
    if code == 137:
        return (
            f"{backend} exited before producing output: terminated by SIGKILL "
            f"(9) — likely killed by an external reaper/OOM, not a resume failure.{suffix}"
        )
    if code != 0:
        return (
            f"{backend} exited before producing output: process exited with code "
            f"{code} — likely a startup or resume error.{suffix}"
        )
    return generic


def _tmux_session_alive(client, chat_id: str) -> bool:
    """Return True if the detached tmux session `cc-<chat_id>` still exists.

    Gates the no-result death report: the SSH tail stream can end while the
    backend process is alive and mid-turn (e.g. a transient disturbance at a
    Lambda handoff), and a false death report lets the next turn's stale
    cleanup kill the healthy session. On SSH errors assume alive so the
    monitor resumes instead of declaring death (HARD_TIMEOUT_SECONDS bounds
    the retries).
    """
    cmd = (
        f"tmux has-session -t {_shell_quote(f'=cc-{chat_id}')} 2>/dev/null "
        f"&& echo alive || echo dead"
    )
    try:
        return _ssh_exec(client, cmd).strip() == "alive"
    except Exception as e:
        logger.warning("tmux liveness check failed for chat {}: {}", chat_id, e)
        return True


def _kill_session_marking_self_killed(client, chat_id: str) -> None:
    """Tear down the detached tmux session for a self-initiated kill (steer
    or interrupt), marking it as self-killed first.

    The `.killed` sentinel is written BEFORE `tmux kill-session`, chained
    with `&&` so the kill only runs if the marker write actually succeeded
    (a failed touch must not be followed by an unmarked kill). Cleanup of
    the stdin/exit files always runs afterward regardless of whether the
    marker+kill chain succeeded. Uses `_ssh_exec` (not fire-and-forget) so
    the caller only proceeds once the remote command has actually
    completed.
    """
    session_name = f"cc-{chat_id}"
    cmd = (
        f"touch /tmp/cc-{chat_id}.killed && "
        f"tmux kill-session -t {_shell_quote(session_name)} 2>/dev/null; "
        f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.exit 2>/dev/null"
    )
    try:
        _ssh_exec(client, cmd)
    except Exception:
        pass


def _consume_self_kill_sentinel(client, chat_id: str) -> bool:
    """Check for and clear the sentinel written by
    `_kill_session_marking_self_killed`.

    Returns True if the session that just produced no result was torn down
    by us, not by an external crash — the no-result branch should resume
    monitoring instead of reporting a death.
    """
    sentinel = f"/tmp/cc-{chat_id}.killed"
    try:
        raw = _ssh_exec(
            client,
            f"test -f {_shell_quote(sentinel)} && echo yes; rm -f {_shell_quote(sentinel)} 2>/dev/null",
        ).strip()
    except Exception:
        return False
    return raw == "yes"


def _pkill_tail_cmd(chat_id: str) -> str:
    """Build a pkill that matches only the remote tail readers of the stdout
    file. The pattern is anchored to the tail cmdline (`tail -n +N -f
    /tmp/cc-<chat_id>.stdout`): the old unanchored `tail.*cc-<chat_id>.stdout`
    form also matched the tmux wrapper shell (its cmdline contains the whole
    `tail ... | <backend> > ....stdout` pipeline), so firing it would kill the
    live turn.
    """
    pattern = f"^tail -n .* -f /tmp/cc-{chat_id}\\.stdout"
    return f"pkill -f {_shell_quote(pattern)} 2>/dev/null"


def _build_tail_cmd(stdout_file: str, exit_file: str, offset: int) -> str:
    """Build the remote tail + watcher command for tailing a detached turn.

    Tails from `offset`, following until the exit file appears. The watcher
    probes the tail pid (`kill -0`) each pass and exits as soon as the tail is
    gone, so killing only the tail (see `_pkill_tail_cmd`) doesn't leave an
    orphan watcher subshell looping until the exit file appears.
    """
    return (
        f"tail -n +{offset + 1} -f {_shell_quote(stdout_file)} & TAIL_PID=$!; "
        f"(while ! test -f {_shell_quote(exit_file)}; do "
        f"kill -0 $TAIL_PID 2>/dev/null || exit; sleep 2; done; "
        f"sleep 1; kill $TAIL_PID 2>/dev/null) & "
        f"wait $TAIL_PID 2>/dev/null"
    )


# ---------------------------------------------------------------------------
# Detached SSH runner (tmux-based, for Lambda timeout resilience)
# ---------------------------------------------------------------------------

def _claude_image_block(image_path: str, client=None) -> Dict:
    if isinstance(image_path, str) and image_path.startswith("s3://"):
        data, media_type = _read_s3_image_for_claude(image_path)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }

    path = Path(image_path).expanduser()
    media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if path.exists():
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    elif client is not None:
        data = _ssh_exec(client, f"base64 -w0 {_shell_quote(str(path))}").strip()
    else:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        },
    }


def _read_s3_image_for_claude(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"invalid s3 image uri: {uri}")
    key = parsed.path.lstrip("/")

    import boto3

    obj = boto3.client("s3").get_object(Bucket=parsed.netloc, Key=key)
    body = obj["Body"].read()
    media_type = obj.get("ContentType") or mimetypes.guess_type(Path(key).name)[0] or "image/jpeg"
    return base64.b64encode(body).decode("ascii"), media_type


def _claude_write_stdin(client, chat_id: str, prompt: str, images: Optional[List[str]] = None) -> None:
    """Write the prompt to /tmp/cc-<chat_id>.stdin as stream-json via SFTP."""
    content = [{"type": "text", "text": prompt}]
    for image_path in images or []:
        content.append(_claude_image_block(image_path, client))

    payload = json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": content,
        },
    }) + "\n"
    sftp = client.open_sftp()
    try:
        with sftp.open(f"/tmp/cc-{chat_id}.stdin", "w") as f:
            f.write(payload)
    finally:
        sftp.close()


def _claude_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `tail -f <stdin> | claude -p --input-format stream-json ...`."""
    full_cmd = cmd + ["--input-format", "stream-json"]
    claude_cmd = " ".join(_shell_quote(c) for c in full_cmd)
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    exec_cmd = f"tail -f -n +1 {_shell_quote(stdin_file)} | {claude_cmd}"
    resume_session_id = _claude_resume_session_id(cmd)
    if not resume_session_id:
        return exec_cmd

    # Claude cleanupPeriodDays can prune old sessions; backup-projects.sh keeps copies.
    restore_snippet = (
        f"_y_sid={_shell_quote(resume_session_id)}; "
        "_y_proj=$(pwd | sed 's|/|-|g'); "
        "_y_dst=\"$HOME/.claude/projects/$_y_proj/$_y_sid.jsonl\"; "
        "_y_src=\"/Users/roy/luohy15/assets/claude-code/projects/$_y_proj/$_y_sid.jsonl\"; "
        "if [ ! -f \"$_y_dst\" ] && [ -f \"$_y_src\" ]; then "
        "mkdir -p \"$(dirname \"$_y_dst\")\"; cp -p \"$_y_src\" \"$_y_dst\"; touch \"$_y_dst\"; "
        "fi; "
    )
    return restore_snippet + exec_cmd


def _claude_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "system":
        return obj.get("session_id")
    return None


def _claude_spec() -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec
    return DetachBackendSpec(
        setup=_claude_write_stdin,
        build_exec=_claude_build_exec,
        parse_initial=_claude_parse_initial,
        upload_images=False,
    )


async def start_detached_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    ssh_client=None,
) -> Optional[str]:
    """Start `claude -p` in a detached tmux session on remote host.

    If `ssh_client` is provided, reuses that connection (from a pool); otherwise
    creates and closes its own connection. Prompt is written via SFTP to a
    stream-json stdin file and piped through `tail -f` into claude. stdout /
    stderr are redirected to `/tmp/cc-<chat_id>.*` files.

    Returns the session_id parsed from the initial `system` event, else None.
    """
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        vm_config=vm_config,
        spec=_claude_spec(),
        env=env,
        images=images,
        ssh_client=ssh_client,
    )


async def tail_ssh_output(
    chat_id: str,
    vm_config: "VmConfig",
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    ssh_client=None,
    check_steer_fn: Optional[Callable[[], List[Tuple[str, str, list]]]] = None,
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
        ssh_client.connect(host, port=port, username=user, pkey=key, timeout=30)

    client = ssh_client
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = StreamConverter(last_message_id=last_message_id)
    result_data = None
    session_id = None
    current_offset = offset
    consumed_steer_ids = []
    stream_error = None
    # Guards the race between a live steer write and turn-end teardown: both
    # _on_steer_detached and _kill_tmux fire independent fire-and-forget SSH
    # commands against the same tmux session/stdin file, so without a shared
    # lock a steer write can land after the session is already killed and
    # silently no-op (see plan-2662-steer-race.md).
    steer_lock = threading.RLock()
    torn_down = False

    try:
        # tail from offset, follow until exit file appears or deadline/interrupt
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset)

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            logger.info("interrupt watchdog (detached): killing tmux session cc-{}", chat_id)
            _kill_session_marking_self_killed(client, chat_id)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass

        def _write_steer(text, msg_id, images=None) -> bool:
            """Write a steer message to the remote stdin pipe and block until
            the write is confirmed to have landed. Must be called while
            holding steer_lock."""
            content = [{"type": "text", "text": text}]
            for image_path in images or []:
                content.append(_claude_image_block(image_path, client))
            payload = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": content,
                },
            })
            _, write_stdout, _ = client.exec_command(
                f"printf '%s\\n' {_shell_quote(payload)} >> {_shell_quote(stdin_file)}"
            )
            exit_code = write_stdout.channel.recv_exit_status()
            if exit_code != 0:
                return False
            converter.last_message_id = msg_id
            consumed_steer_ids.append(msg_id)
            return True

        def _on_steer_detached(text, msg_id, images=None) -> bool:
            with steer_lock:
                if torn_down:
                    return False
                return _write_steer(text, msg_id, images)

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer_detached,
        )
        poll.start()

        def _kill_tmux(self_killed: bool = False):
            """Tear down the tmux session at turn end.

            `self_killed=True` is the interrupt path: it must mark the
            sentinel before killing (same as the watchdog's _kill_detached),
            so a subsequent no-result check can't mistake our own teardown
            for a crash. `self_killed=False` (default) is the normal
            result-completion path: the turn already produced result_data,
            so no no-result branch will run for it and no sentinel is
            needed. Both share the final steer drain/lock behavior.
            """
            nonlocal torn_down
            with steer_lock:
                # Final drain: catch any steer message that landed in the
                # checker between the last poll pass and turn-end, and
                # deliver it before the session goes away.
                if check_steer_fn:
                    try:
                        stragglers = check_steer_fn()
                    except Exception:
                        stragglers = []
                    for msg in stragglers:
                        text, msg_id, images = msg if len(msg) == 3 else (msg[0], msg[1], [])
                        delivered = _write_steer(text, msg_id, images)
                        if not delivered:
                            unclaim = getattr(check_steer_fn, "unclaim", None)
                            if unclaim:
                                unclaim(msg_id)
                torn_down = True
                if self_killed:
                    _kill_session_marking_self_killed(client, chat_id)
                else:
                    try:
                        client.exec_command(
                            f"tmux kill-session -t {_shell_quote(f'cc-{chat_id}')} 2>/dev/null"
                        )
                        client.exec_command(f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.exit 2>/dev/null")
                    except Exception:
                        pass
            try:
                stdout_ch.channel.close()
            except Exception:
                pass

        def _read_lines():
            nonlocal result_data, session_id, current_offset, stream_error
            try:
                for raw_line in stdout_ch:
                    if check_interrupted_fn and check_interrupted_fn():
                        _kill_tmux(self_killed=True)
                        return "interrupted"

                    if check_deadline_fn and check_deadline_fn():
                        try:
                            client.exec_command(_pkill_tail_cmd(chat_id))
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    current_offset += 1

                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    if obj.get("type") == "system":
                        session_id = obj.get("session_id")
                        continue
                    if obj.get("type") == "result":
                        result_data = obj
                        _kill_tmux()
                        return None

                    if message_callback:
                        for msg in converter.process_line(line):
                            message_callback(msg)
            except (OSError, EOFError, Exception) as e:
                if check_interrupted_fn and check_interrupted_fn():
                    return "interrupted"
                if not isinstance(e, (OSError, EOFError)):
                    raise
                stream_error = e

            if check_interrupted_fn and check_interrupted_fn():
                return "interrupted"

            return None

        loop = asyncio.get_event_loop()
        cancelled_result = None
        try:
            exit_reason = await loop.run_in_executor(None, _read_lines)
        except asyncio.CancelledError:
            logger.info("tail_ssh_output cancelled: chat_id={} offset={}", chat_id, current_offset)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass
            cancelled_result = {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": session_id,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
                "consumed_steer_ids": consumed_steer_ids,
            }

        poll.stop()

        if cancelled_result:
            if owns_client:
                client.close()
            return cancelled_result

        # Resolve the no-result outcome while the client is still open: the
        # self-kill sentinel check, tmux liveness check, and exit-code read
        # all need SSH.
        no_result_session_alive = False
        no_result_error = None
        self_killed = False
        if exit_reason is None and result_data is None:
            self_killed = _consume_self_kill_sentinel(client, chat_id)
            if not self_killed:
                no_result_session_alive = _tmux_session_alive(client, chat_id)
                if not no_result_session_alive:
                    no_result_error = _no_result_error_message(client, chat_id, "Claude Code", stream_error)

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
        if result_data is None:
            if self_killed:
                # We tore this session down ourselves (steer/interrupt) —
                # not an external crash. Resume monitoring instead of
                # persisting the generic death report.
                logger.warning(
                    "tail_ssh_output: chat_id={} no result event but session was self-killed (offset={}); suppressing death report",
                    chat_id, current_offset,
                )
                return {
                    "offset": current_offset,
                    "last_message_id": converter.last_message_id,
                    "session_id": session_id,
                    "is_done": False,
                    "result_data": None,
                    "status": "monitoring",
                    "consumed_steer_ids": consumed_steer_ids,
                }
            if no_result_session_alive:
                # The tail stream ended without a `result` event but the tmux
                # session is still alive: the turn is still running (e.g. a
                # transient tail death at a Lambda handoff). Resume monitoring
                # instead of declaring a false death.
                logger.warning(
                    "tail_ssh_output: chat_id={} no result event but tmux session alive (offset={}); resuming monitoring",
                    chat_id, current_offset,
                )
                return {
                    "offset": current_offset,
                    "last_message_id": converter.last_message_id,
                    "session_id": session_id,
                    "is_done": False,
                    "result_data": None,
                    "status": "monitoring",
                    "consumed_steer_ids": consumed_steer_ids,
                }
            # tmux session exited without ever emitting a stream-json `result`
            # event. This can be a startup/resume failure (e.g. `claude -p -r
            # <id>` with a session_id that doesn't exist in the current cwd) or
            # an external SIGTERM/SIGKILL (reaper/OOM). The launcher exit code
            # was read above for a precise message so the chat doesn't
            # silently die.
            logger.warning(
                "tail_ssh_output: chat_id={} exited with no result event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            result_data = {
                "is_error": True,
                "result": no_result_error,
            }
        elif result_data.get("is_error"):
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
