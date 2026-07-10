"""Convert Grok Build CLI streaming-json events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Grok Build headless mode (`grok -p "<prompt>" --output-format streaming-json`)
emits newline-delimited JSON events with these types (live-confirmed against
real successful and failing runs -- see grok_build_probe/findings.md, todo
2734 sub-tasks 1 and the mid-review re-probe):
  - text    : response text delta, {"type":"text","data":"..."}
  - thought : reasoning/thinking delta, {"type":"thought","data":"..."}
  - end     : terminal event, {"type":"end","stopReason":...,"sessionId":...,"requestId":...}
  - error   : {"type":"error","message":"..."}

The CLI does not emit incremental "message start/end" boundaries, so text and
thought deltas are buffered and flushed as a single assistant message on the
terminal `end` (or `error`) event. Tool-call events do not appear on stdout at
all -- a live run that read a file emitted only `text`/`thought` deltas before
and after the (invisible) tool call, so text spanning a tool call lands in the
same buffered message. Unrecognized `type` values are still logged and
skipped rather than raising, as a defensive fallback for any event type not
covered above.
"""

import asyncio
from typing import Callable, Dict, List, Optional

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import (
    parse_stream_line,
    _parse_ssh_target,
    _shell_quote,
    _stream_error_suffix,
    _tmux_session_alive,
    _pkill_tail_cmd,
    _build_tail_cmd,
)
from agent.poll_loop import PollLoop


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    import json
    return json.dumps(value)


class GrokStreamConverter:
    """Stateful JSONL event converter that maps Grok Build events to y-agent messages."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.session_id: Optional[str] = None
        self.model: Optional[str] = None
        self.usage: Dict[str, int] = {}
        self._text_parts: List[str] = []
        self._thought_parts: List[str] = []
        self._text_started = False
        self._pending_text_break = False

    def _emit(self, msg: Message) -> Message:
        msg.parent_id = self.last_message_id
        self.last_message_id = msg.id
        return msg

    def _flush(self) -> List[Message]:
        content = "".join(self._text_parts)
        reasoning = "".join(self._thought_parts) if self._thought_parts else None
        self._text_parts = []
        self._thought_parts = []
        self._text_started = False
        self._pending_text_break = False
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

    def process_line(self, line: str) -> List[Message]:
        obj = parse_stream_line(line)
        if not obj:
            return []

        event_type = obj.get("type")

        if event_type == "text":
            # A thought run sandwiched between two text runs marks an invisible
            # tool call boundary (see module docstring); insert a separator so
            # the resumed text doesn't glue onto the pre-tool-call text.
            if self._pending_text_break:
                self._text_parts.append("\n\n")
                self._pending_text_break = False
            self._text_parts.append(_stringify(obj.get("data")))
            self._text_started = True
            return []

        elif event_type == "thought":
            if self._text_started:
                self._pending_text_break = True
            self._thought_parts.append(_stringify(obj.get("data")))
            return []

        elif event_type == "end":
            session_id = obj.get("sessionId") or obj.get("session_id")
            if session_id:
                self.session_id = session_id
            return self._flush()

        elif event_type == "error":
            logger.warning("grok_build error event: {}", obj.get("message") or obj.get("error") or obj)
            return self._flush()

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
    ssh_client=None,
) -> Optional[str]:
    """Start Grok Build CLI in a detached tmux session on the remote host."""
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        vm_config=vm_config,
        spec=_grok_spec(),
        env=env,
        images=images,
        ssh_client=ssh_client,
    )


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
) -> dict:
    """Tail a detached Grok Build CLI process's stdout file via SSH."""
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

    converter = GrokStreamConverter(last_message_id=last_message_id)
    result_data = None
    last_error_data = None
    current_offset = offset
    steer_msgs = []
    steer_requested = False
    stream_error = None

    try:
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset)
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

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

        def _read_lines():
            nonlocal result_data, last_error_data, current_offset, stream_error
            try:
                for raw_line in stdout_ch:
                    if steer_requested:
                        return "steer"

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

                    if message_callback:
                        for msg in converter.process_line(line):
                            message_callback(msg)
                    else:
                        converter.process_line(line)
            except (OSError, EOFError, Exception) as e:
                if check_interrupted_fn and check_interrupted_fn():
                    return "interrupted"
                if steer_requested:
                    return "steer"
                if not isinstance(e, (OSError, EOFError)):
                    raise
                stream_error = e

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
            logger.info("tail_grok_output cancelled: chat_id={} offset={}", chat_id, current_offset)
            try:
                stdout_ch.channel.close()
            except Exception:
                pass
            cancelled_result = {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
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
                "is_done": True,
                "result_data": None,
                "status": "interrupted",
            }

        if exit_reason == "deadline":
            return {
                "offset": current_offset,
                "last_message_id": converter.last_message_id,
                "session_id": converter.session_id,
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
                    chat_id, current_offset,
                )
                return {
                    "offset": current_offset,
                    "last_message_id": converter.last_message_id,
                    "session_id": converter.session_id,
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
            "is_done": False,
            "result_data": None,
            "status": "error",
        }
