"""Convert Grok Build CLI streaming-json events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Grok Build headless mode (`grok -p "<prompt>" --output-format streaming-json`)
emits newline-delimited JSON events with these types (live-confirmed against
real successful and failing runs -- see grok_build_probe/findings.md, todo
2734 sub-tasks 1 and the mid-review re-probe):
  - text    : response text delta, {"type":"text","data":"..."}
  - thought : reasoning/thinking delta, {"type":"thought","data":"..."}
  - end     : terminal event, {"type":"end","stopReason":...,"sessionId":...,"requestId":...,"usage":{...}}
  - error   : {"type":"error","message":"..."}

The CLI does not emit incremental "message start/end" boundaries, so text and
thought deltas are buffered per step and flushed as an assistant message as
soon as a step boundary is detected (a `thought` arriving after a `text` run
started marks an invisible tool-call boundary -- see `GrokStreamConverter`),
plus a final flush on the terminal `end` (or `error`) event (todo 2813).

Tool-call/tool-result steps do not appear on stdout at all. They are recovered
from a side channel: grok live-appends an ACP (Agent Client Protocol) update
stream to `~/.grok/sessions/<urlencode(cwd)>/<session_id>/updates.jsonl`
(confirmed live via `-s <uuid> -p ... --output-format streaming-json`: the
session dir and `updates.jsonl` are created immediately, before the terminal
`end` event, even on an early failure). `_GrokUpdatesPoller` reads that file
and converts `tool_call` / `tool_call_update` (status=completed) entries into
codex-shaped assistant/tool Messages (todo 2813). Its `poll_once()` is driven
synchronously from the stdout read loop in `tail_grok_output`: it runs after
*every* stdout line is processed (a "relevant segment boundary"), not only
when the stdout channel's blocking read times out idle with no line
available. Reconciling on every line -- not just on an idle gap -- is what
keeps causal order correct even when stdout stays continuously readable: a
`tool_call` recorded between two stdout lines must be drained and its
preceding text flushed before the next line's text starts accumulating, or
the persisted order becomes text -> text -> tool call instead of
text -> tool call -> result -> text. The idle-timeout poll remains as the
only reconciliation point during a genuine mid-tool-call silence (no stdout
line arrives at all). This requires a deterministic session id known
*before* the run starts, which `-s/--session-id <uuid>` on a fresh run
provides (confirmed against grok 0.2.101: `-s` works together with `-p`
headless mode).

Unrecognized `type` values are still logged and skipped rather than raising,
as a defensive fallback for any event type not covered above.
"""

import asyncio
import json
import socket
import threading
import urllib.parse
from typing import Callable, Dict, List, Optional, Set

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import (
    parse_stream_line,
    _parse_ssh_target,
    _shell_quote,
    _ssh_exec,
    _stream_error_suffix,
    _tmux_session_alive,
    _pkill_tail_cmd,
    _build_tail_cmd,
)
from agent.poll_loop import PollLoop

# Grok ACP tool name -> y-agent display name (matches the codex converter's convention).
_GROK_TOOL_NAME_MAP = {
    "run_terminal_command": "Bash",
}

# Give up polling updates.jsonl after this many consecutive misses (the file
# never appearing means an older CLI / layout change / rejected `-s`).
_UPDATES_MAX_MISSING_POLLS = 5
_UPDATES_POLL_INTERVAL_SECONDS = 2.0


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


class GrokStreamConverter:
    """Stateful JSONL event converter that maps Grok Build events to y-agent messages."""

    def __init__(self, last_message_id: Optional[str] = None, session_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.session_id: Optional[str] = session_id
        self.model: Optional[str] = None
        self.usage: Dict[str, int] = {}
        self._text_parts: List[str] = []
        self._thought_parts: List[str] = []
        self._text_started = False

    @property
    def has_pending(self) -> bool:
        """True when a text/thought segment is buffered and not yet flushed.

        Used as a high-water mark: an offset is only safe to persist across a
        Lambda handoff when nothing is buffered, so unflushed content is
        re-read (not lost) by the next invocation.
        """
        return bool(self._text_parts or self._thought_parts)

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        return msg

    def flush(self) -> List[Message]:
        """Flush the buffered text/thought segment into a single assistant Message."""
        content = "".join(self._text_parts)
        reasoning = "".join(self._thought_parts) if self._thought_parts else None
        self._text_parts = []
        self._thought_parts = []
        self._text_started = False
        if not content and not reasoning:
            return []
        msg = Message.from_dict({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "model": self.model,
            "provider": "grok_build",
        })
        return [self._emit(msg)]

    def _extract_usage(self, obj: Dict) -> None:
        usage = obj.get("usage")
        if isinstance(usage, dict):
            self.usage = usage

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        event_type = obj.get("type")

        if event_type == "text":
            self._text_parts.append(_stringify(obj.get("data")))
            self._text_started = True
            return []

        elif event_type == "thought":
            flushed: List[Message] = []
            if self._text_started:
                # A thought run arriving after a text run marks an invisible
                # tool-call boundary (see module docstring): flush the segment
                # so far immediately instead of buffering until turn end.
                flushed = self.flush()
            self._thought_parts.append(_stringify(obj.get("data")))
            return flushed

        elif event_type == "end":
            session_id = obj.get("sessionId") or obj.get("session_id")
            if session_id:
                self.session_id = session_id
            self._extract_usage(obj)
            return self.flush()

        elif event_type == "error":
            logger.warning("grok_build error event: {}", obj.get("message") or obj.get("error") or obj)
            return self.flush()

        else:
            logger.debug("grok_build unknown event type: {}", event_type)
            return []


def _grok_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `<grok cmd...> -p <prompt>`."""
    if images:
        image_lines = "\n".join(f"- {image_path}" for image_path in images)
        suffix = f"Attached image file path(s):\n{image_lines}"
        prompt = f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix
    full_cmd = list(cmd) + ["-p", prompt]
    return " ".join(_shell_quote(c) for c in full_cmd)


def _grok_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "end":
        return obj.get("sessionId") or obj.get("session_id")
    return None


def _grok_spec() -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec
    return DetachBackendSpec(
        build_exec=_grok_build_exec,
        parse_initial=_grok_parse_initial,
    )


async def start_detached_grok_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    bot_config=None,
    ssh_client=None,
) -> Optional[str]:
    """Start Grok Build CLI in a detached tmux session on the remote host."""
    from agent.detach import _start_detached_tmux
    spec = _grok_spec()
    if bot_config and bot_config.base_url:
        from agent.grok_config import build_grok_model_entry, write_grok_config_toml

        alias, entry = build_grok_model_entry(bot_config)
        spec.setup = lambda client, _chat_id, _prompt, _images: write_grok_config_toml(client, alias, entry)
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        vm_config=vm_config,
        spec=spec,
        env=env,
        images=images,
        ssh_client=ssh_client,
    )


def _grok_updates_path(home: str, cwd: str, session_id: str) -> str:
    """Path to the Grok ACP updates.jsonl side channel for a session.

    `~/.grok/sessions/<urlencode(cwd, safe='')>/<session_id>/updates.jsonl`
    (confirmed live on grok 0.2.101: created immediately at session start).
    """
    enc_cwd = urllib.parse.quote(cwd, safe="")
    return f"{home}/.grok/sessions/{enc_cwd}/{session_id}/updates.jsonl"


def _extract_tool_result_text(update: Dict) -> str:
    """Best-effort text extraction from a `tool_call_update` (status=completed)."""
    content_list = update.get("content")
    if isinstance(content_list, list):
        parts = []
        for item in content_list:
            if not isinstance(item, dict):
                continue
            inner = item.get("content")
            if isinstance(inner, dict) and inner.get("text"):
                parts.append(inner["text"])
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    return _stringify(update.get("rawOutput"))


class _GrokUpdatesPoller:
    """Read new tool call/result events from the Grok ACP updates.jsonl side channel.

    `poll_once()` is driven synchronously from the stdout tail loop (see
    `tail_grok_output`), never from an independent background thread: it runs
    after every processed stdout line *and* whenever the stdout reader's
    blocking read times out idle. Reconciling on every line (a "relevant
    segment boundary"), not only on an idle timeout, is what keeps ordering
    correct even when stdout stays continuously readable -- otherwise a
    `tool_call` recorded between two stdout lines could be discovered only
    after later text had already been flushed and emitted. Draining stdout
    up to the current point before ever converting an updates.jsonl event,
    and flushing on a `tool_call`, is what preserves causal order
    (reasoning/text -> tool call -> tool result, matching codex) without
    relying on a cross-thread race. `lock` is still accepted/held for
    defense in depth (e.g. if a future caller drives it from another thread).
    """

    def __init__(
        self,
        client,
        updates_path: str,
        converter: GrokStreamConverter,
        lock: threading.RLock,
        message_callback: Callable[[Message], None],
        offset: int = 0,
        existing_tool_call_ids: Optional[Set[str]] = None,
        existing_tool_result_ids: Optional[Set[str]] = None,
    ):
        self.client = client
        self.updates_path = updates_path
        self.converter = converter
        self.lock = lock
        self.message_callback = message_callback
        # `offset` is the logical, persisted checkpoint: it only advances past
        # complete lines, so a resumed poller (fresh instance, empty `_buf`)
        # can safely restart a `tail -c` read from `offset + 1` without ever
        # re-delivering bytes already folded into a parsed line. `_read_offset`
        # is the physical cursor for the *next* SSH read within this poller's
        # lifetime: it advances by every byte actually read, including a
        # partial trailing line, so that line's bytes are never re-fetched
        # (and duplicated) on the next poll within the same run.
        self.offset = offset
        self._read_offset = offset
        self._buf = ""
        self._pending_tool_calls: Dict[str, Dict] = {}
        # Belt-and-braces dedupe: procs registered before this feature shipped
        # have no persisted updates_offset and restart the poll from byte 0 on
        # a Lambda handoff, so seed already-emitted ids from chat history.
        # Tool calls and their completed results are tracked separately since
        # a legacy replay can contain either half without the other.
        self._seen_tool_call_ids: Set[str] = set(existing_tool_call_ids or ())
        self._seen_tool_result_ids: Set[str] = set(existing_tool_result_ids or ())
        self._missing_polls = 0
        self._available = True

    def poll_once(self) -> None:
        """Synchronous single poll pass: read new bytes, parse+convert complete lines."""
        if not self._available:
            return
        try:
            chunk = _ssh_exec(self.client, f"tail -c +{self._read_offset + 1} {_shell_quote(self.updates_path)} 2>/dev/null")
        except Exception:
            self._missing_polls += 1
            if self._missing_polls == 1:
                logger.info("grok updates.jsonl not yet available at {}", self.updates_path)
            elif self._missing_polls >= _UPDATES_MAX_MISSING_POLLS:
                logger.warning(
                    "grok updates.jsonl unavailable after {} attempts ({}); disabling tool-step side channel",
                    self._missing_polls, self.updates_path,
                )
                self._available = False
            return

        self._missing_polls = 0
        if not chunk:
            return

        # Advance the physical read cursor by every byte actually fetched
        # (whether or not it completes a line) so the next `tail -c` read
        # never re-requests bytes already seen, even mid-line.
        self._read_offset += len(chunk.encode("utf-8"))

        self._buf += chunk
        lines = self._buf.split("\n")
        self._buf = lines[-1]  # keep a partial trailing line (file mid-write) for the next pass
        for line in lines[:-1]:
            self.offset += len(line.encode("utf-8")) + 1
            if line.strip():
                self._process_line(line)

    def _process_line(self, line: str) -> None:
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return
        update = ((obj.get("params") or {}).get("update")) or {}
        kind = update.get("sessionUpdate")
        if kind == "tool_call":
            self._handle_tool_call(update)
        elif kind == "tool_call_update":
            self._handle_tool_call_update(update)
        # agent_message_chunk / agent_thought_chunk / task_backgrounded / etc.
        # are deliberately skipped: text/thought stay on stdout to avoid
        # duplication (see plan-2813-grok-intermediate-stream.md).

    def _handle_tool_call(self, update: Dict) -> None:
        tool_call_id = update.get("toolCallId")
        if not tool_call_id or tool_call_id in self._seen_tool_call_ids:
            return
        self._seen_tool_call_ids.add(tool_call_id)

        raw_name = update.get("title") or "tool"
        raw_input = update.get("rawInput") if isinstance(update.get("rawInput"), dict) else {}
        name = _GROK_TOOL_NAME_MAP.get(raw_name, raw_name)

        arguments = raw_input
        if name == "Bash":
            command = raw_input.get("command") or raw_input.get("cmd") or ""
            arguments = {"command": command}
            if raw_input.get("description"):
                arguments["description"] = raw_input["description"]

        self._pending_tool_calls[tool_call_id] = {"name": name, "arguments": arguments}

        msg = Message.from_dict({
            "role": "assistant",
            "content": "",
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "provider": "grok_build",
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
                "status": "approved",
            }],
        })

        with self.lock:
            # Flush the pending stdout segment first so the visual order is
            # reasoning/text -> tool call -> tool result, matching codex.
            messages = self.converter.flush() + [self.converter._emit(msg)]
            for m in messages:
                self.message_callback(m)

    def _handle_tool_call_update(self, update: Dict) -> None:
        if update.get("status") != "completed":
            # in_progress updates are spammy incremental output; skip.
            return
        tool_call_id = update.get("toolCallId")
        if not tool_call_id or tool_call_id in self._seen_tool_result_ids:
            return
        self._seen_tool_result_ids.add(tool_call_id)
        pending = self._pending_tool_calls.pop(tool_call_id, None)
        name = (pending or {}).get("name") or "tool"
        arguments = (pending or {}).get("arguments") or {}

        msg = Message.from_dict({
            "role": "tool",
            "content": _extract_tool_result_text(update),
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "tool": name,
            "arguments": arguments,
            "tool_call_id": tool_call_id,
        })

        with self.lock:
            messages = [self.converter._emit(msg)]
            for m in messages:
                self.message_callback(m)


async def tail_grok_output(
    chat_id: str,
    vm_config: "VmConfig",
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    check_steer_fn: Optional[Callable[[], List[tuple]]] = None,
    ssh_client=None,
    work_dir: Optional[str] = None,
    session_id: Optional[str] = None,
    updates_offset: int = 0,
    existing_tool_call_ids: Optional[Set[str]] = None,
    existing_tool_result_ids: Optional[Set[str]] = None,
) -> dict:
    """Tail a detached Grok Build CLI process's stdout file via SSH.

    Alongside the stdout tail (text/thought deltas + terminal `end`/`error`,
    unchanged as the completion/error driver), the `updates.jsonl` ACP side
    channel for `session_id` (known up front via deterministic `-s <uuid>` on
    fresh runs) is polled for tool call/result events and converted into
    codex-shaped Messages. The poll is driven synchronously from the stdout
    read loop: after every processed stdout line, and whenever the stdout
    channel's blocking read times out idle. Reconciling after every line (not
    only on an idle gap) guarantees any stdout text/thought already delivered
    is drained (and, on a `tool_call`, flushed) before an updates.jsonl event
    is ever converted, so causal order can't be lost even when stdout stays
    continuously readable with no gap for an idle-only check to catch. If
    `work_dir`/`session_id` are not given, or `updates.jsonl` never appears,
    this degrades gracefully to stdout-only (Layer 1) streaming.
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
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = GrokStreamConverter(last_message_id=last_message_id, session_id=session_id)
    result_data = None
    last_error_data = None
    current_offset = offset
    safe_offset = offset
    steer_msgs = []
    steer_requested = False
    stream_error = None
    # RLock (not Lock): `_poll_updates_and_advance_safe_offset` below holds this
    # lock across `updates_poller.poll_once()`, which itself re-acquires it
    # inside `_handle_tool_call`/`_handle_tool_call_update` when flushing +
    # emitting -- a plain Lock would deadlock on that nested acquisition.
    state_lock = threading.RLock()

    updates_poller: Optional[_GrokUpdatesPoller] = None
    if work_dir and session_id and message_callback:
        try:
            home = _ssh_exec(client, "echo $HOME").strip()
            if home:
                updates_path = _grok_updates_path(home, work_dir, session_id)
                updates_poller = _GrokUpdatesPoller(
                    client, updates_path, converter, state_lock, message_callback,
                    offset=updates_offset, existing_tool_call_ids=existing_tool_call_ids,
                    existing_tool_result_ids=existing_tool_result_ids,
                )
        except Exception as e:
            logger.warning("grok updates.jsonl poller setup failed: {}", e)

    def _final_updates_offset() -> int:
        return updates_poller.offset if updates_poller else updates_offset

    try:
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset)
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        if updates_poller:
            # Bound the blocking stdout read so an idle stretch (no line
            # available yet) periodically times out instead of blocking
            # forever. `_read_lines` also reconciles updates.jsonl after
            # every stdout line; this timeout is only the backstop for a
            # genuine idle gap (no line arrives at all).
            try:
                stdout_ch.channel.settimeout(_UPDATES_POLL_INTERVAL_SECONDS)
            except Exception:
                pass

        def _kill_detached():
            logger.info("interrupt watchdog (grok detached): killing tmux session cc-{}", chat_id)
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

        def _on_steer_detached(text, msg_id, images=None):
            nonlocal steer_requested
            steer_msgs.append((text, msg_id, list(images or [])))
            if steer_requested:
                return
            steer_requested = True
            logger.info("steer (grok detached): killing tmux session cc-{} to resume", chat_id)
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

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer_detached,
        )
        poll.start()

        def _poll_updates_and_advance_safe_offset():
            nonlocal safe_offset
            with state_lock:
                updates_poller.poll_once()
                if not converter.has_pending:
                    # The poller may have flushed a pending stdout segment
                    # (see GrokUpdatesPoller._handle_tool_call): that content
                    # is now persisted/emitted, so it's safe to advance the
                    # stdout high-water mark past every line read so far, not
                    # just the ones that happened to end on a flush boundary.
                    safe_offset = current_offset

        def _read_lines():
            nonlocal result_data, last_error_data, current_offset, safe_offset, stream_error
            stdout_iter = iter(stdout_ch)
            try:
                while True:
                    if steer_requested:
                        return "steer"

                    try:
                        raw_line = next(stdout_iter)
                    except StopIteration:
                        break
                    except socket.timeout:
                        # No stdout line is available right now: every line
                        # that had already arrived over SSH has necessarily
                        # been drained already (this read blocked waiting for
                        # more), so this is a safe point -- and the only
                        # point -- to look at the updates.jsonl side channel.
                        if check_interrupted_fn and check_interrupted_fn():
                            _kill_detached()
                            return "interrupted"
                        if updates_poller:
                            _poll_updates_and_advance_safe_offset()
                        if check_deadline_fn and check_deadline_fn():
                            try:
                                client.exec_command(_pkill_tail_cmd(chat_id))
                            except Exception:
                                pass
                            stdout_ch.channel.close()
                            return "deadline"
                        continue

                    line = raw_line.strip()
                    if not line:
                        continue

                    current_offset += 1

                    if check_interrupted_fn and check_interrupted_fn():
                        _kill_detached()
                        return "interrupted"

                    if check_deadline_fn and check_deadline_fn():
                        try:
                            client.exec_command(_pkill_tail_cmd(chat_id))
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    evt = obj.get("type")
                    if evt == "end":
                        result_data = obj
                    elif evt == "error":
                        last_error_data = {
                            "is_error": True,
                            "result": _stringify(obj.get("message") or obj.get("error") or obj),
                        }

                    with state_lock:
                        messages = converter.process_line(line)
                        if not converter.has_pending:
                            safe_offset = current_offset
                        if message_callback:
                            for msg in messages:
                                message_callback(msg)

                    # Reconcile the updates.jsonl side channel right after this
                    # stdout event, not only when the read times out idle: if
                    # stdout stays continuously readable (no gap ever occurs),
                    # a tool_call recorded between this line and the next must
                    # still be drained -- and flush whatever text is buffered
                    # so far -- before that next line's text starts
                    # accumulating, or causal order (text -> tool call ->
                    # result -> text) breaks even though nothing ever timed
                    # out. The idle-timeout poll below remains the only
                    # opportunity to reconcile during a genuine mid-tool-call
                    # silence (no stdout line arrives at all).
                    if updates_poller:
                        _poll_updates_and_advance_safe_offset()
            except (OSError, EOFError, Exception) as e:
                if check_interrupted_fn and check_interrupted_fn():
                    return "interrupted"
                if steer_requested:
                    return "steer"
                if not isinstance(e, (OSError, EOFError, socket.timeout)):
                    raise
                stream_error = e

            # Catch any trailing updates.jsonl events (e.g. a tool result that
            # completed right around the terminal `end` line) once the stdout
            # side is fully drained.
            if updates_poller:
                try:
                    _poll_updates_and_advance_safe_offset()
                except Exception:
                    pass

            if check_interrupted_fn and check_interrupted_fn():
                return "interrupted"
            if steer_requested:
                return "steer"
            return None

        loop = asyncio.get_event_loop()
        cancelled_result = None
        try:
            exit_reason = await loop.run_in_executor(None, _read_lines)
        except asyncio.CancelledError:
            logger.info("tail_grok_output cancelled: chat_id={} offset={}", chat_id, safe_offset)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass
            cancelled_result = {
                "offset": safe_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
                "updates_offset": _final_updates_offset(),
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
            }

        poll.stop()

        if cancelled_result:
            if owns_client:
                client.close()
            return cancelled_result

        if check_steer_fn and not steer_requested:
            try:
                for msg in check_steer_fn():
                    text, msg_id, images = msg if len(msg) == 3 else (msg[0], msg[1], [])
                    steer_msgs.append((text, msg_id, list(images or [])))
                    steer_requested = True
            except Exception:
                pass

        # Resolve the no-result outcome while the client is still open: the
        # tmux liveness check needs SSH.
        no_result_session_alive = False
        if exit_reason is None and not steer_requested and result_data is None:
            no_result_session_alive = _tmux_session_alive(client, chat_id)

        if owns_client:
            client.close()

        if steer_requested and exit_reason != "interrupted":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
                "updates_offset": _final_updates_offset(),
                "is_done": False,
                "result_data": None,
                "status": "steer",
                "steer_text": "\n\n".join(t for t, _, _ in steer_msgs),
                "steer_images": [image for _, _, images in steer_msgs for image in images],
                "consumed_steer_ids": [mid for _, mid, _ in steer_msgs],
            }

        if exit_reason == "interrupted":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
                "updates_offset": _final_updates_offset(),
                "is_done": True,
                "result_data": None,
                "status": "interrupted",
            }

        if exit_reason == "deadline":
            return {
                "offset": safe_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
                "updates_offset": _final_updates_offset(),
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
            }

        status = "completed"
        if result_data is None:
            if no_result_session_alive:
                # The tail stream ended without an `end` event but the tmux
                # session is still alive: the turn is still running (e.g. a
                # transient tail death at a Lambda handoff). Resume monitoring
                # instead of declaring a false death.
                logger.warning(
                    "tail_grok_output: chat_id={} no end event but tmux session alive (offset={}); resuming monitoring",
                    chat_id, safe_offset,
                )
                return {
                    "offset": safe_offset,
                    "last_message_id": converter.last_message_id,
                    "session_id": converter.session_id,
                    "updates_offset": _final_updates_offset(),
                    "is_done": False,
                    "result_data": None,
                    "status": "monitoring",
                }
            logger.warning(
                "tail_grok_output: chat_id={} exited with no end event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            result_data = {
                "is_error": True,
                "result": (
                    (last_error_data.get("result") if last_error_data else None)
                    or "Grok Build CLI exited before producing an end event."
                ) + _stream_error_suffix(stream_error),
            }
        elif converter.usage:
            result_data = {**result_data, "usage": converter.usage}

        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "session_id": converter.session_id,
            "updates_offset": _final_updates_offset(),
            "is_done": True,
            "result_data": result_data,
            "status": status,
        }

    except Exception as e:
        logger.error("tail_grok_output error: {} {}", type(e).__name__, e)
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id if converter else last_message_id,
            "session_id": converter.session_id if converter else None,
            "updates_offset": _final_updates_offset(),
            "is_done": False,
            "result_data": None,
            "status": "error",
        }
