"""tmux-backed Claude Code TUI backend (backend_type="claude_tui").

A NEW, self-contained path that drives the interactive Claude Code TUI through
tmux, parallel to the `claude -p` stream-json detached path in
`claude_code.py` (which stays byte-for-byte unchanged). The differences:

  - Input: the prompt is pasted into the running TUI via tmux bracketed paste
    (`load-buffer` + `paste-buffer -p` + `send-keys Enter`), not a stream-json
    stdin pipe.
  - Output: assistant state is poll-read from the Claude Code session JSONL
    (`~/.claude/projects/<cwd-dashed>/<uuid>.jsonl`), not a stdout stream. The
    history JSONL carries one content block per line, so consecutive assistant
    records must be merged into a single Message (see `ClaudeTuiStreamConverter`).
  - Auth: launched with no custom base_url / API key, so it uses the EC2
    subscription login (`claude login`).

Lifecycle mirrors the existing backend: one per-turn tmux session keyed
`cc-<chat_id>`, killed on turn completion; deterministic session id via
`--session-id <uuid>` (fresh) / `--resume <uuid>` (continue); live steer via a
mid-turn paste; interrupt = Escape + kill; `_tmux_session_alive` no-result
guard. Only the pure helpers from `claude_code` / `detach` are reused (by
import); the shared stdout-redirect/exit-file skeleton is deliberately not
reused because the TUI path has neither.
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp
from agent.claude_code import (
    parse_stream_line,
    _shell_quote,
    _ssh_exec,
    _stream_error_suffix,
    _tmux_session_alive,
    _convert_user_tool_results,
    _iso_to_unix_ms,
)
from agent.detach import _with_ssh_client, _upload_images
from agent.poll_loop import PollLoop


# How often the tail loop re-reads the JSONL and re-checks completion.
POLL_INTERVAL_SECONDS = 2
# Bound on the fresh-launch dialog dismissal / readiness wait.
READY_TIMEOUT_SECONDS = 90
# Footer that the TUI shows once it is idle and ready for input.
READY_FOOTER = "bypass permissions on"
# Footer suffix shown while the submitted turn is still running.
RUNNING_FOOTER_MARKER = "esc to interrupt"
# Guard against the brief post-submit window before the running footer appears.
IDLE_GUARD_SECONDS = 10
# Sustained (static JSONL offset + idle footer) window before finalizing.
IDLE_FINALIZE_SECONDS = 30


# ---------------------------------------------------------------------------
# Streaming history-JSONL converter (D6)
# ---------------------------------------------------------------------------

class ClaudeTuiStreamConverter:
    """Stateful converter for Claude Code history JSONL, fed line-by-line.

    The history JSONL (read from `~/.claude/projects/`) puts exactly ONE content
    block per line, so consecutive assistant records must be merged into a single
    assistant Message. This mirrors the `_flush_assistant` accumulator inside
    `claude_code.convert_history_session`; that batch function couldn't be reused
    as-is for streaming without changing its (byte-for-byte stable) output, so the
    accumulator is reproduced here as a stateful class. The sub-task-2 unit test
    asserts this converter is equivalent to `convert_history_session` on the same
    assistant + tool_result input.

    Differences from the batch importer, both deliberate for the live path:
      - Standalone `user` *text* records are skipped: the user's prompt and steer
        messages already live in `chat.messages`, so re-emitting them from the
        JSONL would duplicate them. `user` records carrying `tool_result` blocks
        are still emitted (identical to the batch importer).
      - The terminal-turn `usage` block is accumulated (last-wins) for token
        accounting; the final assistant record carries the full turn usage.
    """

    def __init__(self, last_message_id: Optional[str] = None, session_id: Optional[str] = None):
        self.tool_use_index: Dict[str, Dict] = {}
        self.last_message_id = last_message_id
        self.session_id = session_id
        self.work_dir: Optional[str] = None
        self.usage: Dict[str, int] = {}

        # Accumulator for merging consecutive assistant lines.
        self._blocks: List[Dict] = []
        self._model: Optional[str] = None
        self._uuid: Optional[str] = None
        self._ts: Optional[str] = None

    @property
    def has_pending(self) -> bool:
        """True when assistant blocks are buffered and not yet flushed.

        The tail loop uses this as a high-water mark: an offset is only safe to
        persist across a Lambda handoff when no assistant group is mid-merge, so
        the pending lines get re-read (not lost) by the next invocation.
        """
        return bool(self._blocks)

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        return msg

    def flush(self) -> List[Message]:
        """Flush accumulated assistant blocks into a single merged Message."""
        if not self._blocks:
            return []

        text_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls: List[Dict] = []

        for block in self._blocks:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif block_type == "tool_use":
                tool_id = block.get("id")
                tool_name = block.get("name")
                tool_input = block.get("input", {})
                self.tool_use_index[tool_id] = {"name": tool_name, "input": tool_input}
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
        ts = self._ts or get_utc_iso8601_timestamp()
        uuid_val = self._uuid
        model = self._model

        self._blocks = []
        self._model = None
        self._uuid = None
        self._ts = None

        if not content and not reasoning and not tool_calls:
            return []

        msg = Message.from_dict({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning,
            "timestamp": ts,
            "unix_timestamp": _iso_to_unix_ms(ts),
            "id": uuid_val or generate_message_id(),
            "model": model,
            "provider": "claude_code",
            "tool_calls": tool_calls if tool_calls else None,
        })
        return [self._emit(msg)]

    def _accumulate_usage(self, message: Dict) -> None:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return
        for key in ("input_tokens", "output_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens"):
            if usage.get(key) is not None:
                try:
                    self.usage[key] = int(usage[key])
                except (TypeError, ValueError):
                    pass

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        msg_type = obj.get("type")

        # Skip non-message types (same as convert_history_session). The
        # turn-end `system/turn_duration` marker is inspected by the tail loop,
        # not here.
        if msg_type in ("file-history-snapshot", "progress", "system"):
            return []
        if obj.get("isMeta") or obj.get("isSidechain"):
            return []

        if self.session_id is None:
            self.session_id = obj.get("sessionId")
        if self.work_dir is None:
            self.work_dir = obj.get("cwd")

        if msg_type == "assistant":
            message = obj.get("message", {})
            self._accumulate_usage(message)
            if not self._blocks:
                self._model = message.get("model")
                self._uuid = obj.get("uuid")
                self._ts = obj.get("timestamp")
            self._blocks.extend(message.get("content", []))
            return []

        if msg_type == "user":
            # Flush any pending assistant before the user boundary.
            flushed = self.flush()

            message = obj.get("message", {})
            content = message.get("content", "")
            ts = obj.get("timestamp", get_utc_iso8601_timestamp())

            if isinstance(content, str) and (
                content.startswith("<command-name>") or content.startswith("<command-message>")
                or content.startswith("<local-command")
            ):
                return flushed

            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                tool_msgs = _convert_user_tool_results(obj, self.tool_use_index)
                unix_ts = _iso_to_unix_ms(ts)
                for tm in tool_msgs:
                    tm.timestamp = ts
                    tm.unix_timestamp = unix_ts
                    self._emit(tm)
                return flushed + tool_msgs

            # Standalone user *text* (the prompt / a steer) is intentionally
            # dropped: it already exists in chat.messages. (convert_history_session
            # emits it for full-history import; the live path must not duplicate.)
            return flushed

        return []


# ---------------------------------------------------------------------------
# tmux / TUI driving helpers
# ---------------------------------------------------------------------------

def _session(chat_id: str) -> str:
    return f"cc-{chat_id}"


def _prompt_file(chat_id: str) -> str:
    return f"/tmp/cc-{chat_id}.prompt"


def _jsonl_path(home: str, cwd: str, session_id: str) -> str:
    """Path to the Claude Code session JSONL.

    Project dir encoding (A4, spike-confirmed): cwd with every `/` replaced by
    `-`, e.g. `/home/roy/x` -> `-home-roy-x`.
    """
    proj = cwd.replace("/", "-")
    return f"{home}/.claude/projects/{proj}/{session_id}.jsonl"


def _append_image_paths(prompt: str, images: Optional[List[str]]) -> str:
    """Append image file path(s) to the prompt (the TUI has no --image flag)."""
    if not images:
        return prompt
    image_lines = "\n".join(f"- {image_path}" for image_path in images)
    suffix = f"Attached image file path(s):\n{image_lines}"
    return f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix


def _capture_pane(client, chat_id: str) -> str:
    try:
        return _ssh_exec(client, f"tmux capture-pane -p -t {_shell_quote(_session(chat_id))} 2>/dev/null")
    except Exception:
        return ""


def _footer_is_idle(pane: str) -> bool:
    lower = pane.lower()
    return READY_FOOTER in lower and RUNNING_FOOTER_MARKER not in lower


def _send_keys(client, chat_id: str, *keys: str) -> None:
    target = _shell_quote(_session(chat_id))
    for key in keys:
        try:
            client.exec_command(f"tmux send-keys -t {target} {key}")
        except Exception:
            pass


def _paste_prompt(client, chat_id: str, text: str) -> None:
    """Write `text` to the prompt file and bracketed-paste it into the TUI + Enter."""
    sftp = client.open_sftp()
    try:
        with sftp.open(_prompt_file(chat_id), "w") as f:
            f.write(text)
    finally:
        sftp.close()

    buf = _shell_quote(_session(chat_id))
    target = _shell_quote(_session(chat_id))
    pf = _shell_quote(_prompt_file(chat_id))
    _ssh_exec(client, f"tmux load-buffer -b {buf} {pf}")
    # -p = bracketed paste (preserves embedded newlines); -d deletes the buffer.
    _ssh_exec(client, f"tmux paste-buffer -p -d -b {buf} -t {target}")
    # Brief settle so the paste lands before the submit keystroke.
    time.sleep(0.5)
    _ssh_exec(client, f"tmux send-keys -t {target} Enter")


def _tui_kill(client, chat_id: str) -> None:
    """Stop the current turn (Escape) and tear down the tmux session."""
    try:
        client.exec_command(f"tmux send-keys -t {_shell_quote(_session(chat_id))} Escape 2>/dev/null")
    except Exception:
        pass
    try:
        client.exec_command(f"tmux kill-session -t {_shell_quote(_session(chat_id))} 2>/dev/null")
        client.exec_command(f"rm -f {_shell_quote(_prompt_file(chat_id))} 2>/dev/null")
    except Exception:
        pass


async def _wait_ready(client, chat_id: str, dismiss_dialogs: bool, timeout: int = READY_TIMEOUT_SECONDS) -> bool:
    """Poll capture-pane until the ready footer appears, dismissing fresh-launch
    dialogs (D4b) on the way. Returns True if the TUI reached the ready prompt.

    Fresh untrusted-folder launch shows up to three dialogs in order:
      1. folder-trust  -> Enter (default item 1 = trust)
      2. bypass-permissions warning -> Down, Enter (item 2 = accept)
      3. fullscreen-renderer upsell -> Down, Enter (pick "Not now")
    A resume / trusted-folder launch goes straight to the footer.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pane = _capture_pane(client, chat_id)
        lower = pane.lower()

        if READY_FOOTER in lower:
            return True

        if dismiss_dialogs:
            if ("do you trust" in lower or "trust the files" in lower
                    or "project you created" in lower):
                _send_keys(client, chat_id, "Enter")
            elif "yes, i accept" in lower or "no, exit" in lower:
                # Bypass-permissions warning: default is "No, exit"; move to accept.
                _send_keys(client, chat_id, "Down", "Enter")
            elif "fullscreen" in lower:
                _send_keys(client, chat_id, "Down", "Enter")

        await asyncio.sleep(1)

    logger.warning("claude_tui: ready footer not seen within {}s for chat {}", timeout, chat_id)
    return False


def _jsonl_line_count(client, jsonl: str) -> int:
    try:
        out = _ssh_exec(client, f"wc -l < {_shell_quote(jsonl)} 2>/dev/null").strip()
        return int(out) if out else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Detached launcher (D2 / D3 / D4 / D4b)
# ---------------------------------------------------------------------------

async def start_detached_claude_tui_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config,
    session_id: str,
    resume: bool,
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    ssh_client=None,
) -> Tuple[Optional[str], int]:
    """Launch the Claude Code TUI in a `cc-<chat_id>` tmux session and paste the
    prompt.

    `cmd` is the full claude argv (already carrying `--session-id <uuid>` on a
    fresh turn or `--resume <uuid>` on a continue). `session_id` is that same
    uuid, used to locate the session JSONL.

    Returns `(session_id, initial_offset)` where `initial_offset` is the JSONL
    line count recorded just before the prompt is pasted, so the tail reads only
    this turn's new lines (skipping any prior turn on resume).
    """
    with _with_ssh_client(vm_config, ssh_client) as client:
        session_name = _session(chat_id)

        # 1. Stale cleanup (mirror the existing backend's `cc-<chat_id>` cleanup).
        _ssh_exec(
            client,
            f"tmux kill-session -t {_shell_quote(session_name)} 2>/dev/null; "
            f"rm -f {_shell_quote(_prompt_file(chat_id))} 2>/dev/null; "
            f"rm -rf /tmp/cc-{chat_id}-images 2>/dev/null",
        )

        # 2. Validate cwd up front (no exit-file channel to report it later).
        if cwd:
            cwd_exists = _ssh_exec(client, f"test -d {_shell_quote(cwd)} && echo ok || echo missing").strip() == "ok"
            if not cwd_exists:
                raise RuntimeError(f"work_dir not found: {cwd}")

        exec_images = _upload_images(client, chat_id, images) if images else None

        home = _ssh_exec(client, "echo $HOME").strip()
        jsonl = _jsonl_path(home, cwd, session_id) if cwd else None

        # 3. Assemble the tmux inner command: keep EC2 awake, export env, cd, exec.
        inner_parts = [
            "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) &",
        ]
        if env:
            for k, v in env.items():
                inner_parts.append(f"export {k}={_shell_quote(v)};")
        if cwd:
            inner_parts.append(f"cd {_shell_quote(cwd)} &&")
        inner_parts.append("exec " + " ".join(_shell_quote(c) for c in cmd))
        inner = " ".join(inner_parts)

        # 4. Launch the TUI in a detached tmux session (wide pane for capture-pane).
        tmux_cmd = (
            f"tmux new-session -d -s {_shell_quote(session_name)} -x 220 -y 50 "
            + (f"-c {_shell_quote(cwd)} " if cwd else "")
            + _shell_quote(inner)
        )
        _ssh_exec(client, tmux_cmd)

        # 5. Wait for readiness, dismissing the first-launch dialogs on a fresh turn.
        await _wait_ready(client, chat_id, dismiss_dialogs=not resume)

        # 6. Record the JSONL line offset BEFORE pasting, so the tail reads only
        #    this turn's lines (the user prompt line is dropped by the converter).
        initial_offset = _jsonl_line_count(client, jsonl) if jsonl else 0

        # 7. Paste the prompt via bracketed paste + Enter (D4).
        full_prompt = _append_image_paths(prompt, exec_images)
        _paste_prompt(client, chat_id, full_prompt)

        logger.info(
            "claude_tui: launched chat_id={} session_id={} resume={} offset={}",
            chat_id, session_id, resume, initial_offset,
        )
        return session_id, initial_offset


# ---------------------------------------------------------------------------
# Tail / poll-read (D5 / D7 / D8)
# ---------------------------------------------------------------------------

def _is_turn_done(obj: Dict) -> bool:
    """The deterministic turn-end marker (A2): a `system/turn_duration` record
    appended right after the final assistant message."""
    return obj.get("type") == "system" and obj.get("subtype") == "turn_duration"


async def tail_claude_tui_output(
    chat_id: str,
    vm_config,
    work_dir: Optional[str],
    session_id: Optional[str],
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    check_steer_fn: Optional[Callable[[], List[Tuple[str, str, list]]]] = None,
    ssh_client=None,
) -> dict:
    """Poll-read the session JSONL by line offset and stream Messages.

    Each pass reads new complete lines from `offset`, feeds them through a
    `ClaudeTuiStreamConverter`, and advances the offset. Completion is the
    deterministic `system/turn_duration` marker. Steer is a live bracketed
    paste into the running TUI (no kill-restart); interrupt is Escape + kill;
    a Lambda deadline returns `status="monitoring"` with a safe offset.

    Returns the same dict shape as `claude_code.tail_ssh_output`.
    """
    owns_client = ssh_client is None
    if owns_client:
        import io
        import paramiko
        from agent.claude_code import _parse_ssh_target

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(host, port=port, username=user, pkey=key, timeout=30)

    client = ssh_client

    cwd = (work_dir or (vm_config.work_dir if vm_config else None))
    home = _ssh_exec(client, "echo $HOME").strip()
    jsonl = _jsonl_path(home, cwd, session_id) if (cwd and session_id) else None

    converter = ClaudeTuiStreamConverter(last_message_id=last_message_id, session_id=session_id)
    current_offset = offset
    safe_offset = offset
    consumed_steer_ids: List[str] = []
    stream_error: Optional[Exception] = None
    done = False
    emitted_any = False
    tail_start = time.monotonic()
    last_seen_offset = current_offset
    quiescent_since: Optional[float] = None

    # Live steer + interrupt run in the shared poll thread.
    def _on_steer(text, msg_id, images=None):
        try:
            full = _append_image_paths(text, _upload_images(client, chat_id, images) if images else None)
            _paste_prompt(client, chat_id, full)
            converter.last_message_id = msg_id
            consumed_steer_ids.append(msg_id)
            logger.info("claude_tui steer: live-pasted into chat {}", chat_id)
        except Exception as e:
            logger.warning("claude_tui steer paste failed for chat {}: {}", chat_id, e)

    def _on_interrupt():
        logger.info("claude_tui interrupt: Escape + kill tmux for chat {}", chat_id)
        _tui_kill(client, chat_id)

    poll = PollLoop(
        check_interrupted_fn=check_interrupted_fn,
        on_interrupt=_on_interrupt,
        check_steer_fn=check_steer_fn,
        on_steer=_on_steer,
    )
    poll.start()

    def _read_new_lines() -> Optional[str]:
        """Read complete (newline-terminated) JSONL lines from current_offset.

        Returns the raw chunk, or None on an SSH read error (recorded as a
        transient stream error). A partial final line (no trailing newline,
        the file is mid-write) is left unconsumed and re-read next pass.
        """
        nonlocal stream_error
        if not jsonl:
            return ""
        try:
            return _ssh_exec(client, f"tail -n +{current_offset + 1} {_shell_quote(jsonl)} 2>/dev/null")
        except (OSError, EOFError) as e:
            stream_error = e
            return None

    def _emit_messages(messages: List[Message]) -> None:
        nonlocal emitted_any
        if not messages:
            return
        emitted_any = True
        for msg in messages:
            if message_callback:
                message_callback(msg)

    def _drain() -> None:
        """Synchronous read+convert pass (runs in the executor)."""
        nonlocal current_offset, safe_offset, done
        chunk = _read_new_lines()
        if not chunk:
            return
        parts = chunk.split("\n")
        complete = parts[:-1]  # drop the trailing '' (or a partial last line)
        for line in complete:
            current_offset += 1
            obj = parse_stream_line(line)
            if obj and _is_turn_done(obj):
                # Flush the final assistant group, then mark the turn complete.
                _emit_messages(converter.flush())
                safe_offset = current_offset
                done = True
                continue
            _emit_messages(converter.process_line(line))
            if not converter.has_pending:
                safe_offset = current_offset

    status: Optional[str] = None
    try:
        loop = asyncio.get_event_loop()
        try:
            while True:
                if check_interrupted_fn and check_interrupted_fn():
                    _tui_kill(client, chat_id)
                    status = "interrupted"
                    break
                if check_deadline_fn and check_deadline_fn():
                    status = "deadline"
                    break

                await loop.run_in_executor(None, _drain)

                if done:
                    status = "completed"
                    _tui_kill(client, chat_id)
                    break

                # No turn-end marker yet; guard against a dead session (crash).
                if not _tmux_session_alive(client, chat_id):
                    status = "no_result"
                    break

                now = time.monotonic()
                advanced = current_offset > last_seen_offset
                if advanced:
                    quiescent_since = None
                elif now - tail_start >= IDLE_GUARD_SECONDS:
                    pane = _capture_pane(client, chat_id)
                    if _footer_is_idle(pane):
                        if quiescent_since is None:
                            quiescent_since = now
                        elif now - quiescent_since >= IDLE_FINALIZE_SECONDS:
                            status = "stuck_finalize"
                            logger.warning(
                                "claude_tui: idle-footer stuck finalize for chat_id={} offset={}",
                                chat_id,
                                current_offset,
                            )
                            _tui_kill(client, chat_id)
                            break
                    else:
                        quiescent_since = None
                last_seen_offset = current_offset

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("tail_claude_tui_output cancelled: chat_id={} offset={}", chat_id, safe_offset)
            poll.stop()
            if owns_client:
                client.close()
            return {
                "offset": safe_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id or session_id,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
                "consumed_steer_ids": consumed_steer_ids,
            }

        poll.stop()
        if owns_client:
            client.close()

        if status == "interrupted":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id or session_id,
                "is_done": True,
                "result_data": None,
                "status": "interrupted",
                "consumed_steer_ids": consumed_steer_ids,
            }

        if status == "deadline":
            return {
                "offset": safe_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id or session_id,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
                "consumed_steer_ids": consumed_steer_ids,
            }

        if status == "no_result":
            # The tmux session is gone but no turn_duration marker was seen:
            # a startup/resume failure or an external kill (reaper/OOM).
            logger.warning(
                "tail_claude_tui_output: chat_id={} session gone without turn_duration (offset={})",
                chat_id, current_offset,
            )
            return {
                "offset": safe_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id or session_id,
                "is_done": True,
                "result_data": {
                    "is_error": True,
                    "result": (
                        "Claude Code TUI exited before completing the turn "
                        f"(no turn_duration marker).{_stream_error_suffix(stream_error)}"
                    ),
                },
                "status": "error",
                "consumed_steer_ids": consumed_steer_ids,
            }

        if status == "stuck_finalize":
            _emit_messages(converter.flush())
            safe_offset = current_offset
            if emitted_any or converter.usage:
                result_data = {"is_error": False}
                if converter.usage:
                    result_data["usage"] = converter.usage
                return {
                    "offset": current_offset,
                    "last_message_id": converter.last_message_id,
                    "session_id": converter.session_id or session_id,
                    "is_done": True,
                    "result_data": result_data,
                    "status": "completed",
                    "consumed_steer_ids": consumed_steer_ids,
                }
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id or session_id,
                "is_done": True,
                "result_data": {
                    "is_error": True,
                    "result": (
                        "Claude Code TUI went idle without producing output for this turn "
                        f"(no turn_duration marker); finalized after {IDLE_FINALIZE_SECONDS}s. "
                        "Resend or continue."
                    ),
                },
                "status": "error",
                "consumed_steer_ids": consumed_steer_ids,
            }

        # status == "completed"
        result_data = {"is_error": False}
        if converter.usage:
            result_data["usage"] = converter.usage
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "session_id": converter.session_id or session_id,
            "is_done": True,
            "result_data": result_data,
            "status": "completed",
            "consumed_steer_ids": consumed_steer_ids,
        }

    except Exception as e:
        logger.error("tail_claude_tui_output error: {} {}", type(e).__name__, e)
        try:
            poll.stop()
        except Exception:
            pass
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        return {
            "offset": safe_offset,
            "last_message_id": converter.last_message_id if converter else last_message_id,
            "session_id": (converter.session_id if converter else None) or session_id,
            "is_done": False,
            "result_data": None,
            "status": "error",
            "consumed_steer_ids": consumed_steer_ids,
        }
