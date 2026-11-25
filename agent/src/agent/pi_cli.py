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
    parse_stream_line, _shell_quote, _tmux_session_alive,
    _kill_session_marking_self_killed, _consume_self_kill_sentinel,
    _pkill_tail_cmd, _build_tail_cmd,
)
from agent.input_ledger import InputLedger
from agent.poll_loop import PollLoop
from agent.startup_diagnostic import read_attempt_diagnostic


def _complete_launch_group(ledger, launch_input_uuid):
    if launch_input_uuid and launch_input_uuid in ledger.groups:
        ledger.observe_lifecycle({"state": "completed", "command_uuid": launch_input_uuid})


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
            self.terminal = True
            if obj.get("aborted"):
                self.error = self.error or "pi run aborted"
        elif event_type in ("agent_start", "auto_retry_start", "auto_compaction_start", "compaction_start"):
            self.end_candidate = None
            self.terminal = False
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


def _pi_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `<pi cmd...> <prompt>` (pi takes the prompt as a positional message)."""
    if images:
        image_lines = "\n".join(f"- {image_path}" for image_path in images)
        suffix = f"Attached image file path(s):\n{image_lines}"
        prompt = f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix
    full_cmd = list(cmd) + ["--", prompt]
    return " ".join(_shell_quote(c) for c in full_cmd) + " < /dev/null"


def _pi_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "session":
        return obj.get("id")
    return None


async def start_detached_pi_ssh(cmd, prompt, cwd, chat_id, node, env=None,
                                images=None, ssh_client=None, unset_env=None,
                                provider=None):
    """Stage only this bot's provider before launching on the selected node."""
    from agent.detach import DetachBackendSpec, _start_detached_tmux
    from agent.pi_models import stage_pi_provider

    def setup(client, chat_id, prompt, images):
        stage_pi_provider(client, provider, (env or {}).get("PI_CODING_AGENT_DIR"))

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
    """Tail pi, settling only after retries; steer kills and closes the launch group."""
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
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
        _complete_launch_group(ledger, launch_input_uuid)
    if _restore_pi_pending(converter, result_data):
        result_data = None
    current_offset = offset
    stream_error = None
    poll = None
    # Guards the steer/interrupt teardown against the reader's own ledger
    # update: both the poll thread and the reader may retire the launch group.
    steer_lock = threading.RLock()
    torn_down = False
    steered = threading.Event()

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

        def _on_steer(text, msg_id, images=None) -> bool:
            """End the turn so the closeout continuation answers this message.

            A True return claims the message for this run. The message itself
            stays in the chat, so closeout selects it as pending input and the
            next turn resumes the same thread with it. A False return releases
            the claim: no thread to resume yet, or the session could not be
            confirmed dead.
            """
            nonlocal torn_down
            with steer_lock:
                if torn_down:
                    return False
                if not converter.session_id:
                    return False
                if not _kill_session_marking_self_killed(client, chat_id, node=node):
                    return False
                torn_down = True
                # The launch prompt was consumed by the turn being ended, so
                # closeout must not treat it as an owed input.
                _complete_launch_group(ledger, launch_input_uuid)
                steered.set()
                try:
                    stdout_ch.channel.close()
                except Exception:
                    pass
            logger.info("pi steer: ended turn chat_id={} for message={}", chat_id, msg_id)
            return True

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer,
        )
        poll.start()

        def _read_lines():
            nonlocal result_data, current_offset, stream_error, torn_down
            try:
                for raw_line in stdout_ch:
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

                    for msg in converter.process_line(line):
                        if message_callback:
                            message_callback(msg)
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
        cancelled_result = None
        try:
            exit_reason = await loop.run_in_executor(None, _read_lines)
        except asyncio.CancelledError:
            logger.info("tail_pi_output cancelled: chat_id={} offset={}", chat_id, current_offset)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass
            cancelled_result = _view(False, "monitoring", result_data)

        poll.stop()

        if cancelled_result:
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            return cancelled_result

        if steered.is_set() and exit_reason != "interrupted" and result_data is None:
            # Our own steer kill ended the turn before it completed. This is
            # not a death: consume the sentinel so no later check misreads it,
            # and report a completed turn so the closeout continuation
            # relaunches the same thread with the pending message.
            _consume_self_kill_sentinel(client, chat_id)
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            logger.info("tail_pi_output: chat_id={} turn ended by steer at offset={}", chat_id, current_offset)
            return _view(True, "completed", None)

        if (exit_reason is None and result_data is None and converter.end_candidate
                and stream_error is None and not steered.is_set()
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
