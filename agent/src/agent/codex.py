"""Convert OpenAI Codex CLI JSONL events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Codex `codex exec --json` emits JSONL events:
  - thread.started  : thread_id
  - turn.started    : new turn begins
  - item.started    : tool/message item begins
  - item.completed  : tool/message item finishes
  - turn.completed  : usage stats; the launch input group completes here
  - turn.failed     : fatal turn error
  - error           : fatal top-level error

`item.completed` of `type=error` (unknown model metadata) is ignored. It is
not a failed turn. `codex exec` has no live input channel: a mid-run message
ends the current turn (the tmux session is killed) and the locked closeout
relaunches the same thread with that message as the next prompt.
"""

import asyncio
import json
import re
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
from agent.poll_loop import PollLoop

JSONValue = Optional[object]

_SHELL_WRAPPER_RE = re.compile(
    r'^(/\S+/(?:bash|zsh|sh|fish|dash))\s+-\w*c\s+(.+)$',
    re.DOTALL,
)


def _strip_shell_wrapper(command: str) -> str:
    """Strip shell wrapper (e.g. '/usr/bin/zsh -lc pwd') to extract the actual command."""
    match = _SHELL_WRAPPER_RE.match(command)
    if match:
        inner = match.group(2)
        if (inner.startswith("'") and inner.endswith("'")) or \
           (inner.startswith('"') and inner.endswith('"')):
            inner = inner[1:-1]
        return inner
    return command


def _json_string(value: JSONValue) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _command_output(item: Dict) -> str:
    output = item.get("aggregated_output")
    if output is None:
        output = item.get("output", "")
    text = _json_string(output)
    exit_code = item.get("exit_code")
    status = item.get("status")
    if exit_code not in (None, 0) or (status and status != "completed"):
        parts = []
        if exit_code is not None:
            parts.append(f"exit_code={exit_code}")
        if status:
            parts.append(f"status={status}")
        suffix = f"[codex command {' '.join(parts)}]"
        return f"{text.rstrip()}\n{suffix}" if text else suffix
    return text


def _file_change_arguments(item: Dict) -> Dict:
    raw_changes = item.get("changes")
    changes = raw_changes if isinstance(raw_changes, list) else []
    normalized_changes = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        path = change.get("path") or change.get("file_path") or ""
        kind = change.get("kind") or change.get("type") or "change"
        normalized = {"path": path, "kind": kind}
        for key, value in change.items():
            if key not in normalized and key not in ("file_path", "type"):
                normalized[key] = value
        normalized_changes.append(normalized)

    first_path = ""
    if normalized_changes:
        first_path = str(normalized_changes[0].get("path") or "")
    else:
        first_path = str(item.get("file_path") or item.get("path") or "")

    args: Dict = {"file_path": first_path}
    if first_path:
        args["path"] = first_path
    if normalized_changes:
        args["changes"] = normalized_changes
    return args


def _file_change_summary(item: Dict) -> str:
    args = _file_change_arguments(item)
    changes = args.get("changes")
    if isinstance(changes, list) and changes:
        lines = []
        for change in changes:
            if not isinstance(change, dict):
                continue
            kind = str(change.get("kind") or "change")
            path = str(change.get("path") or "")
            lines.append(f"{kind} {path}".strip())
        return "\n".join(lines)
    path = str(args.get("file_path") or "")
    return f"changed {path}".strip() if path else "file changed"


def _complete_launch_group(ledger: InputLedger, launch_input_uuid: Optional[str]) -> None:
    """Retire the launch write when Codex finishes the turn.

    Codex has no command_lifecycle events. `turn.completed` is the evidence
    that the single launch prompt was consumed.
    """
    if not launch_input_uuid or launch_input_uuid not in ledger.groups:
        return
    ledger.observe_lifecycle({"state": "completed", "command_uuid": launch_input_uuid})


class CodexStreamConverter:
    """Stateful JSONL event converter that maps Codex events to y-agent Messages."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.thread_id: Optional[str] = None
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.num_turns: int = 0
        self.has_usable_output: bool = False
        self._pending_items: Dict[str, str] = {}

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        self.has_usable_output = True
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
                arguments = _file_change_arguments(item)
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
                            "arguments": json.dumps(arguments),
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

            if item_type == "error":
                # Unknown model metadata and similar item errors are not fatal.
                return messages

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
                output = _command_output(item)
                command = _strip_shell_wrapper(item.get("command", ""))
                msg = Message.from_dict({
                    "role": "tool",
                    "content": output,
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "tool": "Bash",
                    "arguments": {"command": command},
                    "tool_call_id": tool_call_id,
                })
                messages.append(self._emit(msg))

            elif item_type == "file_change":
                content = item.get("diff", "") or item.get("content", "") or _file_change_summary(item)
                arguments = _file_change_arguments(item)
                msg = Message.from_dict({
                    "role": "tool",
                    "content": content if isinstance(content, str) else json.dumps(content),
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "tool": "Edit",
                    "arguments": arguments,
                    "tool_call_id": tool_call_id,
                })
                messages.append(self._emit(msg))
            # reasoning and other item types stay out of the transcript. Only
            # agent_message is the user-visible assistant text.

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


def _codex_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `codex ... -- <prompt> < /dev/null`.

    `--` keeps a prompt that starts with `-` from being parsed as a flag.
    Piped stdin makes `codex exec` block on "Reading additional input from stdin".
    """
    full_cmd = list(cmd)
    for image_path in images or []:
        full_cmd.extend(["--image", image_path])
    full_cmd.append("--")
    full_cmd.append(prompt)
    quoted = " ".join(_shell_quote(part) for part in full_cmd)
    return f"{quoted} < /dev/null"


def _codex_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "thread.started":
        return obj.get("thread_id")
    return None


def _codex_spec() -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec
    return DetachBackendSpec(
        build_exec=_codex_build_exec,
        parse_initial=_codex_parse_initial,
    )


async def start_detached_codex_ssh(
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
    """Start `codex exec` in a detached tmux session on the chat's node.

    Codex takes the prompt as a positional argument and does not read
    stream-json stdin. stdout / stderr / exit files use `/tmp/cc-<chat_id>.*`.

    Returns the thread_id from the initial `thread.started` event, else None.
    """
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        node=node,
        spec=_codex_spec(),
        env=env,
        images=images,
        ssh_client=ssh_client,
        unset_env=unset_env,
    )


async def tail_codex_output(
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
) -> dict:
    """Tail a detached codex process's stdout file via SSH.

    `check_steer_fn` supplies messages accepted mid-run. `codex exec` has no
    live input channel, so a steer ends the turn: the session is killed, the
    launch input group is retired, and the message stays pending for the
    closeout continuation, which resumes the same thread with it. Interrupt
    keeps priority. `turn.completed` marks the launch input group completed;
    otherwise anything that arrived during the run stays outstanding.

    Fatal only on a top-level `error` or `turn.failed`, or on a session that
    exits without `turn.completed` (a self-kill for steer or interrupt is not
    a death).
    """
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = CodexStreamConverter(last_message_id=last_message_id)
    ledger = input_ledger if input_ledger is not None else InputLedger(chat_id)
    result_data = pending_result if isinstance(pending_result, dict) else None
    if result_data and result_data.get("type") == "turn.completed" and not result_data.get("is_error"):
        _complete_launch_group(ledger, launch_input_uuid)
    last_error_data = None
    current_offset = offset
    stream_error = None
    poll = None
    # Guards the steer/interrupt teardown against the reader's own ledger
    # update: both the poll thread and the reader may retire the launch group.
    steer_lock = threading.RLock()
    torn_down = False
    steered = threading.Event()

    def _view(is_done: bool, status: str, data=None) -> dict:
        thread_id = converter.thread_id
        return {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "thread_id": thread_id,
            "session_id": thread_id,
            "is_done": is_done,
            "result_data": data,
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
            logger.info("interrupt watchdog (codex detached): killing tmux session cc-{}", chat_id)
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
                if not converter.thread_id:
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
            logger.info("codex steer: ended turn chat_id={} for message={}", chat_id, msg_id)
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
                    if not obj:
                        continue

                    evt = obj.get("type")
                    if evt == "thread.started" and obj.get("thread_id"):
                        converter.thread_id = obj.get("thread_id")

                    if evt == "turn.completed":
                        result_data = obj
                        with steer_lock:
                            _complete_launch_group(ledger, launch_input_uuid)
                        converter.process_line(line)
                        continue

                    if evt == "turn.failed":
                        last_error_data = {
                            "is_error": True,
                            "result": (obj.get("error") or {}).get("message") or "Turn failed",
                        }
                        converter.process_line(line)
                        continue
                    if evt == "error":
                        last_error_data = {
                            "is_error": True,
                            "result": obj.get("message") or "Unknown error",
                        }
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
            logger.info("tail_codex_output cancelled: chat_id={} offset={}", chat_id, current_offset)
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

        if steered.is_set() and exit_reason != "interrupted" and result_data is None and last_error_data is None:
            # Our own steer kill ended the turn before it completed. This is
            # not a death: consume the sentinel so no later check misreads it,
            # and report a completed turn so the closeout continuation
            # relaunches the same thread with the pending message.
            _consume_self_kill_sentinel(client, chat_id)
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            logger.info("tail_codex_output: chat_id={} turn ended by steer at offset={}", chat_id, current_offset)
            return _view(True, "completed", None)

        no_result_session_alive = False
        no_result_error = None
        self_killed = False
        if exit_reason is None and result_data is None and last_error_data is None:
            self_killed = _consume_self_kill_sentinel(client, chat_id)
            if not self_killed:
                no_result_session_alive = _tmux_session_alive(client, chat_id, node=node)
                if not no_result_session_alive:
                    no_result_error = _no_result_error_message(client, chat_id, "Codex", stream_error, node=node)

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
                    "tail_codex_output: chat_id={} no turn.completed event but session still in play (offset={}); resuming monitoring",
                    chat_id, current_offset,
                )
                return _view(False, "monitoring", None)
            logger.warning(
                "tail_codex_output: chat_id={} exited with no turn.completed event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            data = {"is_error": True, "result": no_result_error or "Codex exited before producing a turn."}

        return _view(True, status, data)

    except Exception as exc:
        logger.error("tail_codex_output error: {} {}", type(exc).__name__, exc)
        if poll is not None:
            poll.stop()
        if owns_client:
            try:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            except Exception:
                pass
        return _view(False, "error", None)
