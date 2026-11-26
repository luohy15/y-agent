"""pi JSON event conversion and detached execution, with retry-aware completion."""

import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
from loguru import logger
from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import (
    parse_stream_line, _shell_quote, _ssh_exec, _tmux_session_alive,
    _kill_session_marking_self_killed, _consume_self_kill_sentinel,
    _pkill_tail_cmd, _build_tail_cmd,
)
from agent.input_ledger import ACKNOWLEDGED, InputLedger, native_input_uuid
from agent.poll_loop import PollLoop
from agent.startup_diagnostic import read_attempt_diagnostic


def _complete_launch_group(ledger, launch_input_uuid):
    if launch_input_uuid and launch_input_uuid in ledger.groups:
        ledger.observe_lifecycle({"state": "completed", "command_uuid": launch_input_uuid})


def _complete_open_groups(ledger, launch_input_uuid=None):
    """Retire the inputs pi acknowledged before `agent_settled`.

    pi checks its steering queue before emitting `agent_settled`, so a steer
    whose `success:true` response precedes the settle in stdout was drained.
    A steer still `SUBMITTED` when the settle is read was written after pi
    settled (or before pi read it) and was NOT consumed: a successful file
    write is not evidence of consumption, so it stays outstanding for closeout
    to re-deliver. A pre-upgrade record may carry no response at all for the
    launch prompt; complete that group only when no lifecycle was observed.
    """
    for command_uuid, message_ids in ledger.groups.items():
        acknowledged = any(ledger.state_of(mid) == ACKNOWLEDGED for mid in message_ids)
        legacy_launch = command_uuid == launch_input_uuid and not ledger.lifecycle_observed
        if acknowledged or legacy_launch:
            ledger.observe_lifecycle({"state": "completed", "command_uuid": command_uuid})


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _assistant_text(content) -> str:
    """Join the `text` parts of an assistant message, skipping thinking/toolCall."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(_stringify(part.get("text", "")))
        return "\n".join(p for p in parts if p)
    return _stringify(content)


def _tool_result_text(result) -> str:
    """Extract text from a `tool_execution_end` result ({content: [{type,text}]})."""
    if result is None:
        return ""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(_stringify(part.get("text", part.get("content", ""))))
                else:
                    parts.append(_stringify(part))
            return "\n".join(p for p in parts if p)
        return _stringify(content if content is not None else result)
    return _stringify(result)


def _pi_observed_at(message) -> Optional[str]:
    """Aware ISO time of the response end: request start plus its duration."""
    stamp = message.get("timestamp")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    duration = message.get("durationMs")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
        duration = 0
    try:
        when = datetime.fromtimestamp((stamp + duration) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return when.isoformat()


def _pi_context_usage(message) -> Optional[Dict]:
    """Prompt occupancy of one assistant response, in the shared counter names.

    Pi reports `input` (cache-exclusive), `cacheRead`, `cacheWrite` and
    `output`. Missing or malformed counters stay unknown. Only the latest
    assistant observation is kept, so the final request of the turn wins.
    """
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    def counter(name):
        value = usage.get(name)
        return value if type(value) is int and value >= 0 else None

    result = {
        "input_tokens": counter("input"),
        "output_tokens": counter("output"),
        "cache_read_tokens": counter("cacheRead"),
        "cache_creation_tokens": counter("cacheWrite"),
    }
    observed = any(value is not None for value in result.values())
    result["usage_state"] = "observed" if observed else "missing"
    result["observed_at"] = _pi_observed_at(message) if observed else None
    return result


class PiStreamConverter:
    """Stateful JSONL event converter that maps pi json-mode events to y-agent messages."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.session_id: Optional[str] = None
        self.model: Optional[str] = None
        self.context_usage: Optional[Dict] = None
        self.has_usable_output = False
        self.terminal = False
        self.settled = False
        self.end_candidate = None
        self.error = None
        self._pending_tools: Dict[str, Dict] = {}

    def _emit(self, msg: Message) -> Message:
        self.has_usable_output = True
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        return msg

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        event_type = obj.get("type")
        messages: List[Message] = []

        if event_type == "session":
            self.session_id = obj.get("id") or self.session_id

        elif event_type == "message_end":
            message = obj.get("message") or {}
            if message.get("role") != "assistant":
                return []
            self.error = (message.get("errorMessage") or "pi assistant failed") if message.get("stopReason") in ("error", "aborted") else None
            self.model = message.get("model") or self.model
            observed_usage = _pi_context_usage(message)
            if observed_usage is not None:
                self.context_usage = observed_usage
            content = _assistant_text(message.get("content"))
            if content:
                msg = Message.from_dict({
                    "role": "assistant",
                    "content": content,
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "model": message.get("model") or self.model,
                    "provider": "pi",
                })
                messages.append(self._emit(msg))

        elif event_type == "tool_execution_start":
            tool_call_id = obj.get("toolCallId") or generate_message_id()
            tool_name = obj.get("toolName") or "tool"
            parameters = obj.get("args")
            if parameters is None:
                parameters = {}

            self._pending_tools[tool_call_id] = {"name": tool_name, "parameters": parameters}
            msg = Message.from_dict({
                "role": "assistant",
                "content": "",
                "timestamp": get_utc_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": generate_message_id(),
                "model": self.model,
                "provider": "pi",
                "tool_calls": [{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(parameters),
                    },
                    "status": "approved",
                }],
            })
            messages.append(self._emit(msg))

        elif event_type == "tool_execution_end":
            tool_call_id = obj.get("toolCallId")
            tool_info = self._pending_tools.pop(tool_call_id, {}) if tool_call_id else {}
            tool_name = obj.get("toolName") or tool_info.get("name")
            parameters = tool_info.get("parameters")
            content = _tool_result_text(obj.get("result"))
            if obj.get("isError"):
                suffix = "[pi tool error]"
                content = f"{content}\n{suffix}" if content else suffix

            msg = Message.from_dict({
                "role": "tool",
                "content": content,
                "timestamp": get_utc_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": generate_message_id(),
                "tool": tool_name,
                "arguments": parameters,
                "tool_call_id": tool_call_id,
            })
            messages.append(self._emit(msg))

        elif event_type == "agent_end":
            # A retry/compaction may follow. Only EOF or agent_settled can settle it.
            self.end_candidate = obj.get("willRetry") is False
        elif event_type == "result" and obj.get("is_error"):
            # The shared detached launcher emits this when cwd is missing.
            self.terminal = True
            self.error = obj.get("result") or "pi launch failed"
        elif event_type == "agent_settled":
            # No retry, compaction or queued message remains: the turn is over.
            self.terminal = True
            self.settled = True
            if obj.get("aborted"):
                self.error = self.error or "pi run aborted"
        elif event_type == "response":
            # Command responses are correlated in the tail, which owns the
            # input ledger; the converter only maps session events.
            pass
        elif event_type in ("agent_start", "auto_retry_start", "auto_compaction_start", "compaction_start"):
            self.end_candidate = None
            self.terminal = False
            self.settled = False
        else:
            logger.debug("pi unhandled event type: {}", event_type)

        return messages


def _pi_pending_state(converter: "PiStreamConverter", data=None) -> dict:
    """Tentative end state persisted across a Lambda handoff.

    Any carried `context_usage` rides along, so a settled-but-paused view keeps
    the turn's final-request usage on the next invocation.
    """
    payload = dict(data) if isinstance(data, dict) else {
        "type": "pi_pending", "end_candidate": converter.end_candidate,
        "error": converter.error,
    }
    payload.setdefault("context_usage", converter.context_usage)
    return payload


def _restore_pi_pending(converter: "PiStreamConverter", result_data) -> bool:
    """Restore such a state, including the carried usage. True when it was one."""
    if not result_data or result_data.get("type") != "pi_pending":
        return False
    converter.end_candidate = result_data.get("end_candidate")
    converter.error = result_data.get("error")
    carried = result_data.get("context_usage")
    if isinstance(carried, dict):
        converter.context_usage = carried
    return True


def _pi_prompt_text(prompt: str, images: Optional[List[str]] = None) -> str:
    """Fold attached image paths into the prompt text (no native image blocks)."""
    if images:
        image_lines = "\n".join(f"- {image_path}" for image_path in images)
        suffix = f"Attached image file path(s):\n{image_lines}"
        return f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix
    return prompt


def _pi_launch_payload(chat_id: str, prompt: str, images: Optional[List[str]] = None,
                       input_uuid: Optional[str] = None) -> str:
    """The three JSONL commands written to the stdin file before launch.

    `get_state` supplies the session id (RPC mode emits no session header),
    `set_steering_mode all` matches Claude Code's batched steer delivery, and
    `prompt` carries the folded launch input. Each command has a stable id so
    its response can be correlated across a Lambda handoff.
    """
    launch_uuid = input_uuid or native_input_uuid(chat_id, "launch")
    commands = [
        {"id": native_input_uuid(chat_id, "get_state"), "type": "get_state"},
        {"id": native_input_uuid(chat_id, "set_steering_mode"),
         "type": "set_steering_mode", "mode": "all"},
        {"id": launch_uuid, "type": "prompt", "message": _pi_prompt_text(prompt, images)},
    ]
    return "".join(json.dumps(command) + "\n" for command in commands)


def _pi_steer_payload(chat_id: str, msg_id: str, text: str,
                      images: Optional[List[str]] = None) -> str:
    """One `steer` command line; the id is the input's native identity.

    No trailing newline: `_on_steer` writes it with `printf '%s\\n'`, and a
    second newline would make pi emit a `parse` error for the empty line.
    """
    return json.dumps({
        "id": native_input_uuid(chat_id, msg_id),
        "type": "steer",
        "message": _pi_prompt_text(text, images),
    })


def _pi_write_stdin(client, chat_id: str, prompt: str, images: Optional[List[str]] = None,
                    input_uuid: Optional[str] = None) -> None:
    """Write the launch commands to /tmp/cc-<chat_id>.stdin via SFTP."""
    payload = _pi_launch_payload(chat_id, prompt, images, input_uuid)
    sftp = client.open_sftp()
    try:
        with sftp.open(f"/tmp/cc-{chat_id}.stdin", "w") as f:
            f.write(payload)
    finally:
        sftp.close()


def _pi_upload_steer_images(client, chat_id: str, msg_id: str,
                            images: Optional[List[str]]) -> List[str]:
    """Stage a steer's images under a per-message subdirectory (shared helper)."""
    from agent.detach import upload_steer_images

    return upload_steer_images(client, chat_id, msg_id, images)


def _pi_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `tail -f <stdin> | pi --mode rpc ...` with tail cleanup.

    The prompt and its image paths are written to the stdin file by setup, so
    the command carries no positional prompt. The pipeline is backgrounded so
    the wrapper can stop the tail once pi exits; the wrapper's exit status is
    pi's, which the shared launcher records in the exit file.
    """
    pi_cmd = " ".join(_shell_quote(c) for c in cmd)
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    stdin_tail_pattern = _shell_quote(f"^tail -f -n \\+1 /tmp/cc-{chat_id}\\.stdin$")
    return (
        f"( tail -f -n +1 {_shell_quote(stdin_file)} | {pi_cmd} & _y_pi=$!; "
        "while kill -0 $_y_pi 2>/dev/null; do sleep 0.2; done; "
        f"pkill -f {stdin_tail_pattern} 2>/dev/null; "
        "wait $_y_pi )"
    )


def _pi_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "session":
        return obj.get("id")
    if obj.get("type") == "response" and obj.get("command") == "get_state":
        data = obj.get("data")
        session_id = data.get("sessionId") if isinstance(data, dict) else None
        return session_id if isinstance(session_id, str) and session_id else None
    return None


async def start_detached_pi_ssh(cmd, prompt, cwd, chat_id, node, env=None,
                                images=None, ssh_client=None, unset_env=None,
                                provider=None, input_uuid=None):
    """Stage this bot's provider and the RPC launch commands before launching."""
    from agent.detach import DetachBackendSpec, _start_detached_tmux
    from agent.pi_models import stage_pi_provider

    def setup(client, chat_id, prompt, images):
        stage_pi_provider(client, provider, (env or {}).get("PI_CODING_AGENT_DIR"))
        _pi_write_stdin(client, chat_id, prompt, images, input_uuid=input_uuid)

    return await _start_detached_tmux(
        cmd=cmd, prompt=prompt, cwd=cwd, chat_id=chat_id, node=node,
        spec=DetachBackendSpec(build_exec=_pi_build_exec, parse_initial=_pi_parse_initial, setup=setup),
        env=env, images=images, ssh_client=ssh_client, unset_env=unset_env,
    )


async def tail_pi_output(
    chat_id: str,
    node,
    offset: int = 0,
    last_message_id: Optional[str] = None,
    message_callback: Optional[Callable[[Message], None]] = None,
    check_interrupted_fn: Optional[Callable[[], bool]] = None,
    check_deadline_fn: Optional[Callable[[], bool]] = None,
    check_steer_fn: Optional[Callable[[], List[Tuple[str, str, list]]]] = None,
    ssh_client=None,
    input_ledger: Optional[InputLedger] = None,
    launch_input_uuid: Optional[str] = None,
    pending_result: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Tail pi's RPC session; steer is queued in place and `agent_settled` ends it."""
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = PiStreamConverter(last_message_id=last_message_id)
    converter.session_id = session_id
    ledger = input_ledger if input_ledger is not None else InputLedger(chat_id)
    result_data = pending_result if isinstance(pending_result, dict) else None
    if isinstance(result_data, dict):
        carried_usage = result_data.get("context_usage")
        if isinstance(carried_usage, dict):
            converter.context_usage = carried_usage
    if result_data and result_data.get("type") == "agent_settled":
        converter.terminal = True
        converter.error = result_data.get("result") if result_data.get("is_error") else None
        _complete_open_groups(ledger, launch_input_uuid)
    if _restore_pi_pending(converter, result_data):
        result_data = None
    current_offset = offset
    stream_error = None
    poll = None
    # Guards the steer write and the settle teardown: a steer must never be
    # appended after the session was torn down, and a settle must not retire an
    # input the poll thread is still writing.
    steer_lock = threading.RLock()
    torn_down = False
    # Set by a Lambda-deadline cancellation before the reader is joined, so no
    # steer write or settle teardown can land after the handoff snapshot.
    reader_stop = threading.Event()

    def _view(is_done: bool, status: str, data=None) -> dict:
        session_id = converter.session_id
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "session_id": session_id,
            "is_done": is_done,
            "result_data": data,
            "status": status,
            "delivery_states": ledger.states,
            "input_groups": ledger.groups,
            "lifecycle_observed": ledger.lifecycle_observed,
            "has_usable_output": converter.has_usable_output,
            "context_usage": converter.context_usage,
            "pending_result": None if is_done else _pi_pending_state(converter, data),
        }

    try:
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset, node=node)
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            nonlocal torn_down
            logger.info("interrupt watchdog (pi detached): killing tmux session cc-{}", chat_id)
            with steer_lock:
                torn_down = True
                _kill_session_marking_self_killed(client, chat_id, node=node)
                try:
                    stdout_ch.channel.close()
                except Exception:
                    pass

        def _teardown_session():
            """Kill the long-lived RPC session after a settle.

            A settle is a clean end, not a death, so no self-kill sentinel is
            written. The kill is synchronous: the process is gone before
            closeout can launch a continuation beside it.
            """
            try:
                from agent.detach import _tmux_kill_cmd
                _ssh_exec(client, _tmux_kill_cmd(chat_id, node=node))
            except Exception as exc:
                logger.warning("pi settle teardown failed chat_id={}: {}", chat_id, exc)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass

        def _on_steer(text, msg_id, images=None) -> bool:
            """Append a steer command to the live RPC stdin pipe.

            The turn is not ended: pi delivers the message after the current
            assistant turn finishes its tool calls, before the next LLM call.
            A zero write status only proves the bytes reached the file; the
            command's `response` promotes it to acknowledged, and
            `agent_settled` retires it. A False return releases the poll
            checker's claim so closeout re-delivers the message.
            """
            with steer_lock:
                if torn_down or reader_stop.is_set() or converter.settled:
                    return False
                try:
                    remote_images = _pi_upload_steer_images(client, chat_id, msg_id, images)
                except Exception as exc:
                    logger.warning("pi steer image staging failed chat_id={} message={}: {}",
                                   chat_id, msg_id, exc)
                    return False
                payload = _pi_steer_payload(chat_id, msg_id, text, remote_images)
                _, write_stdout, _ = client.exec_command(
                    f"printf '%s\\n' {_shell_quote(payload)} >> {_shell_quote(stdin_file)}"
                )
                if write_stdout.channel.recv_exit_status() != 0:
                    return False
                converter.last_message_id = msg_id
                ledger.mark_submitted(native_input_uuid(chat_id, msg_id), [msg_id])
            logger.info("pi steer: queued chat_id={} for message={}", chat_id, msg_id)
            return True

        def _handle_response(obj) -> Optional[str]:
            """Correlate a command response with the ledger; return a prompt refusal."""
            command = obj.get("command")
            command_id = obj.get("id")
            success = obj.get("success") is True
            if command == "get_state":
                data = obj.get("data")
                session_id = data.get("sessionId") if isinstance(data, dict) else None
                if isinstance(session_id, str) and session_id:
                    converter.session_id = session_id
                return None
            if command in ("prompt", "steer") and command_id and command_id in ledger.groups:
                with steer_lock:
                    ledger.observe_lifecycle({
                        "state": "queued" if success else "refused",
                        "command_uuid": command_id,
                    })
                if command == "prompt" and not success:
                    return obj.get("error") or "pi rejected the prompt"
            return None

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer,
        )
        poll.start()

        def _read_lines():
            nonlocal result_data, current_offset, stream_error, torn_down
            if result_data is not None:
                # A handoff carried a terminal result: the turn is already over,
                # so tear the long-lived session down before tailing anything.
                with steer_lock:
                    if reader_stop.is_set():
                        return "deadline"
                    torn_down = True
                    _teardown_session()
                return None
            try:
                for raw_line in stdout_ch:
                    if reader_stop.is_set():
                        return "deadline"
                    line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="replace").strip()
                    if check_interrupted_fn and check_interrupted_fn():
                        with steer_lock:
                            torn_down = True
                            _kill_session_marking_self_killed(client, chat_id, node=node)
                            stdout_ch.channel.close()
                        return "interrupted"

                    if check_deadline_fn and check_deadline_fn():
                        try:
                            client.exec_command(_pkill_tail_cmd(chat_id))
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    current_offset += 1
                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    prompt_error = (_handle_response(obj)
                                    if obj.get("type") == "response" else None)
                    for msg in converter.process_line(line):
                        if message_callback:
                            message_callback(msg)

                    if prompt_error is not None:
                        # pi refused the launch prompt before starting a run, so
                        # no agent_settled will follow; end the turn here.
                        result_data = {"type": "agent_settled", "is_error": True,
                                       "result": prompt_error}
                        with steer_lock:
                            if reader_stop.is_set():
                                return "deadline"
                            torn_down = True
                            _teardown_session()
                        return None

                    if converter.settled:
                        # No retry, compaction or queued message remains: the
                        # turn is over and the long-lived session can go.
                        result_data = {"type": "agent_settled", "is_error": bool(converter.error),
                                       "result": converter.error or ""}
                        with steer_lock:
                            if reader_stop.is_set():
                                return "deadline"
                            torn_down = True
                            _complete_open_groups(ledger, launch_input_uuid)
                            _teardown_session()
                        return None

                    # Persist tentative end state across Lambda handoffs, but do
                    # not retire inputs or report success until settled/clean EOF.
                    if converter.terminal:
                        result_data = {"type": "agent_settled", "is_error": bool(converter.error),
                                       "result": converter.error or ""}
                        with steer_lock:
                            _complete_launch_group(ledger, launch_input_uuid)
                    else:
                        result_data = None
            except (OSError, EOFError, Exception) as exc:
                if check_interrupted_fn and check_interrupted_fn():
                    return "interrupted"
                if not isinstance(exc, (OSError, EOFError)):
                    raise
                stream_error = exc

            if check_interrupted_fn and check_interrupted_fn():
                return "interrupted"
            return None

        loop = asyncio.get_event_loop()
        reader = loop.run_in_executor(None, _read_lines)
        cancelled = False
        try:
            exit_reason = await asyncio.shield(reader)
        except asyncio.CancelledError:
            logger.info("tail_pi_output cancelled: chat_id={} offset={}", chat_id, current_offset)
            reader_stop.set()
            try:
                stdout_ch.channel.close()
            except Exception:
                pass
            cancelled = True
            # Closing a channel does not stop a buffered-line callback. Join
            # the shielded reader before checkpointing its offset and ledger.
            while not reader.done():
                try:
                    await asyncio.shield(reader)
                except asyncio.CancelledError:
                    continue
            reader.result()

        poll.stop(timeout=None)
        with steer_lock:
            # Prevent a poll callback waiting behind an in-flight write from
            # submitting after the handoff snapshot is taken.
            torn_down = True

        if cancelled:
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            return _view(False, "monitoring", result_data)

        if (exit_reason is None and result_data is None and converter.end_candidate
                and stream_error is None
                and not _tmux_session_alive(client, chat_id, node=node)):
            attempt = read_attempt_diagnostic(client, chat_id, backend="pi")
            if attempt["exit_code"] == 0:
                result_data = {"type": "agent_settled", "is_error": bool(converter.error),
                               "result": converter.error or ""}
                _complete_launch_group(ledger, launch_input_uuid)

        no_result_session_alive = False
        no_result_error = None
        self_killed = False
        if exit_reason is None and result_data is None:
            self_killed = _consume_self_kill_sentinel(client, chat_id)
            if not self_killed:
                no_result_session_alive = _tmux_session_alive(client, chat_id, node=node)
                if not no_result_session_alive:
                    attempt = read_attempt_diagnostic(client, chat_id, stream_error, backend="pi")
                    no_result_error = attempt["text"]

        if owns_client:
            from agent.chat_target import close_owned_client
            close_owned_client(client)

        if exit_reason == "interrupted":
            return _view(True, "interrupted", None)

        if exit_reason == "deadline":
            return _view(False, "monitoring", result_data)

        status = "completed"
        data = result_data
        if result_data is None:
            if self_killed or no_result_session_alive:
                logger.warning(
                    "tail_pi_output: chat_id={} no agent_settled event but session still in play (offset={}); resuming monitoring",
                    chat_id, current_offset,
                )
                return _view(False, "monitoring", None)
            logger.warning(
                "tail_pi_output: chat_id={} exited with no agent_settled event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            data = {"is_error": True, "result": no_result_error or "pi exited before producing a turn."}

        if data and data.get("is_error"):
            status = "error"
        return _view(True, status, data)

    except Exception as exc:
        logger.error("tail_pi_output error: {} {}", type(exc).__name__, exc)
        if poll is not None:
            poll.stop()
        if owns_client:
            try:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            except Exception:
                pass
        return _view(False, "error", None)
