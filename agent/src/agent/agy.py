"""Convert Antigravity CLI stream-json events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

`agy -p` with `--output-format stream-json` emits one JSON object per line:

  - init        : conversation_id, once
  - step_update : user_input, agent_response, tool, or checkpoint
  - result      : terminal status and cumulative usage

`input_tokens` already excludes cache, and `thinking_tokens` is already inside
`output_tokens` (documented total = input + output). A mid-run message ends
the turn: `agy -p` has no live stdin channel, so the tmux session is killed
and closeout relaunches with `--conversation`.
"""

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from agent.detach import DetachBackendSpec

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import (
    parse_stream_line,
    _shell_quote,
    _no_result_error_message,
    _tmux_session_alive,
    _kill_session_marking_self_killed,
    _consume_self_kill_sentinel,
    _pkill_tail_cmd,
    _build_tail_cmd,
)
from agent.input_ledger import InputLedger

IMAGE_UNSUPPORTED = "agy does not support image input"


def normalize_usage(usage) -> dict:
    """Turn counters in the shared schema.

    Antigravity already reports cache-exclusive input and folds thinking into
    output. Subtracting cache or adding thinking would mis-count the documented
    sample, whose total is input + output. Missing or malformed counters stay
    unknown. There is no cache-write field.
    """
    usage = usage if isinstance(usage, dict) else {}

    def counter(name):
        value = usage.get(name)
        return value if type(value) is int and 0 <= value <= 2_147_483_647 else None

    result = {
        "input_tokens": counter("input_tokens"),
        "output_tokens": counter("output_tokens"),
        "cache_creation_tokens": None,
        "cache_read_tokens": counter("cache_read_tokens"),
    }
    result["usage_state"] = "observed" if any(value is not None for value in result.values()) else "missing"
    return result


def successful_result(data) -> Optional[dict]:
    """Inner object of a SUCCESS result event, else None."""
    if not isinstance(data, dict) or data.get("is_error") or data.get("event") != "result":
        return None
    inner = data.get("result")
    if not isinstance(inner, dict) or inner.get("status") != "SUCCESS":
        return None
    return inner


def result_error_text(obj) -> Optional[str]:
    """Error text for a failed result, or for the detach work_dir sentinel.

    A SUCCESS result and ordinary step lines return None.
    """
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "error" and not obj.get("event"):
        message = obj.get("message")
        return message if isinstance(message, str) and message else "agy failed"
    if obj.get("event") != "result":
        return None
    inner = obj.get("result")
    inner = inner if isinstance(inner, dict) else {}
    status = inner.get("status")
    if status in (None, "SUCCESS"):
        return None
    error = inner.get("error")
    if isinstance(error, str) and error:
        return error
    return f"agy status {status}"


def _conversation_id(obj) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    sources = (obj, obj.get("step_update"), obj.get("result"), obj.get("init"))
    for source in sources:
        if not isinstance(source, dict):
            continue
        cid = source.get("conversation_id")
        if isinstance(cid, str) and cid:
            return cid
    return None


def _step_key(step: Dict, fallback: str) -> object:
    index = step.get("step_index")
    if type(index) is int:
        return index
    return fallback


def _tool_output(info: Dict) -> str:
    output = info.get("output")
    if isinstance(output, str):
        text = output
    elif output is None:
        text = ""
    else:
        text = json.dumps(output)
    error = info.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or "tool error"
        suffix = f"[agy tool error] {message}"
        return f"{text.rstrip()}\n{suffix}" if text else suffix
    if isinstance(error, str) and error:
        return f"{text.rstrip()}\n{error}" if text else error
    return text


def _tool_view(step: Dict) -> Tuple[str, Dict, str]:
    info = step.get("tool_info")
    info = info if isinstance(info, dict) else {}
    raw_name = step.get("tool_name") or info.get("name") or "tool"
    params = info.get("parameters")
    params = params if isinstance(params, dict) else {}
    if raw_name == "run_command":
        command = params.get("CommandLine")
        if command is None:
            command = params.get("command", "")
        if not isinstance(command, str):
            command = json.dumps(command)
        return "Bash", {"command": command}, _tool_output(info)
    return str(raw_name), params, _tool_output(info)


def _complete_launch_group(ledger: InputLedger, launch_input_uuid: Optional[str]) -> None:
    """Retire the launch write when agy finishes the turn.

    `agy -p` has no command_lifecycle events. A SUCCESS result is the evidence
    that the single launch prompt was consumed.
    """
    if not launch_input_uuid or launch_input_uuid not in ledger.groups:
        return
    ledger.observe_lifecycle({"state": "completed", "command_uuid": launch_input_uuid})


class AgyStreamConverter:
    """Stateful NDJSON converter. One tool step is one tool call; response
    deltas for one step collapse into one assistant message."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.conversation_id: Optional[str] = None
        self.model: Optional[str] = None
        # result.usage is conversation-cumulative; the last agent_response
        # step's usage is that request's own occupancy and is what a context
        # badge should show.
        self.usage = normalize_usage(None)
        self.request_usage: Optional[Dict] = None
        self.has_usable_output: bool = False
        self._text: Dict[object, List[str]] = {}
        self._tool_calls: Dict[object, str] = {}
        self._tool_done: set = set()
        self._saw_assistant_text = False
        self._anon = 0
        self._anon_ids: Dict[int, str] = {}

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        self.has_usable_output = True
        return msg

    def _key(self, step: Dict) -> object:
        """Same step dict keeps one key. A missing step_index cannot join two lines."""
        key = _step_key(step, "")
        if key != "":
            return key
        cached = self._anon_ids.get(id(step))
        if cached is None:
            self._anon += 1
            cached = f"anon-{self._anon}"
            self._anon_ids[id(step)] = cached
        return cached

    def _assistant(self, content: str, tool_calls=None) -> Message:
        payload = {
            "role": "assistant",
            "content": content,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
            "provider": "agy",
        }
        if self.model:
            payload["model"] = self.model
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return Message.from_dict(payload)

    def _remember_text(self, step: Dict) -> None:
        delta = step.get("text_delta")
        if isinstance(delta, str) and delta:
            self._text.setdefault(self._key(step), []).append(delta)

    def _flush_text(self, step: Dict) -> Optional[Message]:
        text = "".join(self._text.pop(self._key(step), []))
        if not text:
            return None
        self._saw_assistant_text = True
        return self._emit(self._assistant(text))

    def _tool_step(self, step: Dict, state: str) -> List[Message]:
        key = self._key(step)
        name, arguments, output = _tool_view(step)
        messages: List[Message] = []
        call_id = self._tool_calls.get(key)
        known = state == "DONE" or bool(arguments.get("command")) or (name != "Bash" and bool(arguments))
        if call_id is None and known:
            call_id = f"agy-step-{key}" if type(key) is int else generate_message_id()
            self._tool_calls[key] = call_id
            messages.append(self._emit(self._assistant("", [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
                "status": "approved",
            }])))
        if state == "DONE" and key not in self._tool_done:
            self._tool_done.add(key)
            messages.append(self._emit(Message.from_dict({
                "role": "tool",
                "content": output,
                "timestamp": get_utc_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": generate_message_id(),
                "tool": name,
                "arguments": arguments,
                "tool_call_id": call_id,
            })))
        return messages

    def _step(self, step: Dict) -> List[Message]:
        if not isinstance(step, dict):
            return []
        step_type = step.get("step_type")
        state = step.get("state")
        if step_type in ("user_input", "checkpoint"):
            return []
        if step_type == "tool":
            return self._tool_step(step, state if isinstance(state, str) else "")
        if step_type == "agent_response":
            step_usage = step.get("usage")
            if isinstance(step_usage, dict):
                observed = normalize_usage(step_usage)
                if observed.get("usage_state") == "observed":
                    self.request_usage = observed
            self._remember_text(step)
            if state == "DONE":
                flushed = self._flush_text(step)
                return [flushed] if flushed else []
            return []
        return []

    def _result(self, obj: Dict) -> List[Message]:
        inner = obj.get("result")
        inner = inner if isinstance(inner, dict) else {}
        cid = _conversation_id(obj)
        if cid:
            self.conversation_id = cid
        if inner.get("status") == "SUCCESS":
            self.usage = normalize_usage(inner.get("usage"))
        if inner.get("status") != "SUCCESS" or self._saw_assistant_text:
            return []
        text = inner.get("response")
        if not isinstance(text, str) or not text:
            return []
        self._saw_assistant_text = True
        return [self._emit(self._assistant(text))]

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not isinstance(obj, dict):
            return []
        cid = _conversation_id(obj)
        if cid:
            self.conversation_id = cid
        event = obj.get("event")
        if event == "init":
            init_info = obj.get("init")
            if isinstance(init_info, dict) and isinstance(init_info.get("model"), str):
                self.model = init_info["model"]
            return []
        if event == "step_update":
            return self._step(obj.get("step_update"))
        if event == "result":
            return self._result(obj)
        if result_error_text(obj):
            logger.error("agy error event: {}", result_error_text(obj))
        return []


def build_agy_argv(model: Optional[str] = None, conversation_id: Optional[str] = None,
                   effort: Optional[str] = None) -> List[str]:
    """Headless argv without the prompt. `-p` is added by `_agy_build_exec`.

    The model is the plain id (`gemini-4-neon`); the level is a separate
    `--effort` flag, because a suffixed id such as `gemini-4-neon-low`
    conflicts with `--effort`.
    """
    cmd = ["agy", "--output-format", "stream-json"]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    cmd.append("--dangerously-skip-permissions")
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])
    return cmd


def _agy_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """`agy -p <prompt> ... < /dev/null`.

    Closing stdin keeps print mode from waiting on a streaming input session.
    Images have no flag on this CLI.
    """
    if images:
        raise ValueError(IMAGE_UNSUPPORTED)
    argv = list(cmd) or ["agy"]
    full = [argv[0], "-p", prompt, *argv[1:]]
    quoted = " ".join(_shell_quote(part) for part in full)
    return f"{quoted} < /dev/null"


def _agy_parse_initial(obj: Dict) -> Optional[str]:
    if isinstance(obj, dict) and obj.get("event") == "init":
        return _conversation_id(obj)
    return None


def _agy_spec() -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec
    return DetachBackendSpec(
        build_exec=_agy_build_exec,
        parse_initial=_agy_parse_initial,
        upload_images=False,
    )


async def start_detached_agy_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    node,
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    ssh_client=None,
    unset_env: Optional[List[str]] = None,
) -> Optional[str]:
    """Start `agy -p` in a detached tmux session on the chat's node.

    Returns the conversation_id from the initial `init` event, else None.
    """
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        node=node,
        spec=_agy_spec(),
        env=env,
        images=images,
        ssh_client=ssh_client,
        unset_env=unset_env,
    )


async def tail_agy_output(
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
    conversation_id: Optional[str] = None,
) -> dict:
    """Tail a detached agy process's stdout file via SSH.

    A steer ends the turn once `init` has named a conversation. Closeout
    relaunches that conversation with the pending message. Interrupt keeps
    priority. A non-SUCCESS result, a detach sentinel, or an exit with no
    result is fatal. A self-kill for steer or interrupt is not a death.

    `conversation_id` seeds the converter with the id persisted by a previous
    invocation, so a resumed tail (Lambda handoff at `offset > 0`, whose new
    stdout lines may lag the steer check) accepts a steer immediately instead
    of waiting for another `init` line.
    """
    from agent.poll_loop import PollLoop

    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = AgyStreamConverter(last_message_id=last_message_id)
    if conversation_id:
        converter.conversation_id = conversation_id
    ledger = input_ledger if input_ledger is not None else InputLedger(chat_id)
    result_data = pending_result if isinstance(pending_result, dict) else None
    replay = successful_result(result_data)
    if replay is not None:
        _complete_launch_group(ledger, launch_input_uuid)
        converter.usage = normalize_usage(replay.get("usage"))
        replay_id = _conversation_id(result_data)
        if replay_id:
            converter.conversation_id = replay_id
    last_error_data = None
    current_offset = offset
    stream_error = None
    poll = None
    steer_lock = threading.RLock()
    torn_down = False
    steered = threading.Event()

    def _view(is_done: bool, status: str, data=None) -> dict:
        conversation_id = converter.conversation_id
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "conversation_id": conversation_id,
            "thread_id": conversation_id,
            "session_id": conversation_id,
            "is_done": is_done,
            "result_data": data,
            "usage": converter.usage,
            "request_usage": converter.request_usage,
            "status": status,
            "delivery_states": ledger.states,
            "input_groups": ledger.groups,
            "lifecycle_observed": ledger.lifecycle_observed,
            "has_usable_output": converter.has_usable_output,
            "pending_result": None if is_done else data,
        }

    try:
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset, node=node)
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            nonlocal torn_down
            logger.info("interrupt watchdog (agy detached): killing tmux session cc-{}", chat_id)
            with steer_lock:
                torn_down = True
                _kill_session_marking_self_killed(client, chat_id, node=node)
                try:
                    stdout_ch.channel.close()
                except Exception:
                    pass

        def _on_steer(text, msg_id, images=None) -> bool:
            """End the turn so closeout resumes `--conversation` with this message."""
            nonlocal torn_down
            with steer_lock:
                if torn_down or not converter.conversation_id:
                    return False
                # The turn already produced its own terminal result, so there is
                # nothing to steer and the kill would only confuse closeout.
                if result_data is not None or last_error_data is not None:
                    return False
                if not _kill_session_marking_self_killed(client, chat_id, node=node):
                    return False
                torn_down = True
                _complete_launch_group(ledger, launch_input_uuid)
                steered.set()
                try:
                    stdout_ch.channel.close()
                except Exception:
                    pass
            logger.info("agy steer: ended turn chat_id={} for message={}", chat_id, msg_id)
            return True

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_kill_detached,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer,
        )
        poll.start()

        def _read_lines():
            nonlocal result_data, last_error_data, current_offset, stream_error, torn_down
            try:
                for raw_line in stdout_ch:
                    line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    current_offset += 1

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

                    obj = parse_stream_line(line)
                    if not isinstance(obj, dict):
                        continue

                    cid = _conversation_id(obj)
                    if cid:
                        converter.conversation_id = cid

                    if obj.get("event") == "result":
                        error_text = result_error_text(obj)
                        if error_text is None and successful_result(obj) is not None:
                            result_data = obj
                            with steer_lock:
                                _complete_launch_group(ledger, launch_input_uuid)
                            produced = converter.process_line(line)
                            if message_callback:
                                for msg in produced:
                                    message_callback(msg)
                            continue
                        last_error_data = {
                            "is_error": True,
                            "result": error_text or "agy result missing status",
                        }
                        converter.process_line(line)
                        continue

                    error_text = result_error_text(obj)
                    if error_text is not None:
                        last_error_data = {"is_error": True, "result": error_text}
                        converter.process_line(line)
                        continue

                    if message_callback:
                        for msg in converter.process_line(line):
                            message_callback(msg)
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
            logger.info("tail_agy_output cancelled: chat_id={} offset={}", chat_id, current_offset)
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

        # Steer success is decided by our own teardown: `_on_steer` only tears
        # down a turn that had no result yet. `agy` flushes a result event with
        # `status: ERROR, finished_reason: interrupted` while it handles our
        # SIGTERM, so a `last_error_data` seen after the steer is that flush,
        # not a turn failure. It must not become a fatal error (todo 4472).
        if steered.is_set() and exit_reason != "interrupted" and result_data is None:
            _consume_self_kill_sentinel(client, chat_id)
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            logger.info("tail_agy_output: chat_id={} turn ended by steer at offset={}", chat_id, current_offset)
            return _view(True, "completed", None)

        no_result_session_alive = False
        no_result_error = None
        self_killed = False
        if exit_reason is None and result_data is None and last_error_data is None:
            self_killed = _consume_self_kill_sentinel(client, chat_id)
            if not self_killed:
                no_result_session_alive = _tmux_session_alive(client, chat_id, node=node)
                if not no_result_session_alive:
                    no_result_error = _no_result_error_message(client, chat_id, "Antigravity", stream_error, node=node)

        if owns_client:
            from agent.chat_target import close_owned_client
            close_owned_client(client)

        if exit_reason == "interrupted":
            return _view(True, "interrupted", None)

        if exit_reason == "deadline":
            return _view(False, "monitoring", result_data)

        status = "completed"
        data = result_data
        if last_error_data:
            status = "error"
            data = last_error_data
        elif result_data is None:
            if self_killed or no_result_session_alive:
                logger.warning(
                    "tail_agy_output: chat_id={} no result event but session still in play (offset={}); resuming monitoring",
                    chat_id, current_offset,
                )
                return _view(False, "monitoring", None)
            logger.warning(
                "tail_agy_output: chat_id={} exited with no result event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            data = {"is_error": True, "result": no_result_error or "Antigravity CLI exited before producing a result."}

        return _view(True, status, data)

    except Exception as exc:
        logger.error("tail_agy_output error: {} {}", type(exc).__name__, exc)
        if poll is not None:
            poll.stop()
        if owns_client:
            try:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            except Exception:
                pass
        return _view(False, "error", None)
