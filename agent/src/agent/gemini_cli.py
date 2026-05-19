"""Convert Gemini CLI stream-json events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Gemini CLI headless mode emits newline-delimited JSON events with these types:
  - init        : session metadata (session_id, model)
  - message     : user/assistant message chunks
  - tool_use    : tool call requests with parameters
  - tool_result : output from executed tools
  - error       : non-fatal warnings and system errors
  - result      : final outcome with stats
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import parse_stream_line, _parse_ssh_target, _shell_quote
from agent.poll_loop import PollLoop


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" or "text" in part:
                    parts.append(_stringify(part.get("text", "")))
                elif "content" in part:
                    parts.append(_stringify(part.get("content")))
            else:
                parts.append(_stringify(part))
        return "\n".join(p for p in parts if p)
    return _stringify(content)


def _usage_from_stats(stats: Dict) -> Dict[str, int]:
    if not isinstance(stats, dict):
        return {}

    usage = {}
    input_tokens = (
        stats.get("input_tokens")
        or stats.get("inputTokens")
        or stats.get("prompt_tokens")
        or stats.get("promptTokens")
    )
    output_tokens = (
        stats.get("output_tokens")
        or stats.get("outputTokens")
        or stats.get("completion_tokens")
        or stats.get("completionTokens")
    )

    models = stats.get("models")
    if isinstance(models, dict):
        for model_stats in models.values():
            if not isinstance(model_stats, dict):
                continue
            tokens = model_stats.get("tokens")
            if isinstance(tokens, dict):
                input_tokens = input_tokens or tokens.get("input") or tokens.get("prompt")
                output_tokens = output_tokens or tokens.get("output") or tokens.get("completion")
            input_tokens = input_tokens or model_stats.get("input_tokens") or model_stats.get("inputTokens")
            output_tokens = output_tokens or model_stats.get("output_tokens") or model_stats.get("outputTokens")

    if input_tokens is not None:
        usage["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        usage["output_tokens"] = int(output_tokens)
    return usage


class GeminiStreamConverter:
    """Stateful JSONL event converter that maps Gemini CLI events to y-agent messages."""

    def __init__(self, last_message_id: Optional[str] = None):
        self.last_message_id = last_message_id
        self.session_id: Optional[str] = None
        self.model: Optional[str] = None
        self.usage: Dict[str, int] = {}
        self._pending_tools: Dict[str, Dict] = {}

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

        if event_type == "init":
            self.session_id = obj.get("session_id") or obj.get("sessionId") or obj.get("id")
            self.model = obj.get("model") or self.model

        elif event_type == "message":
            role = obj.get("role")
            if role != "assistant":
                return []
            content = _content_text(obj.get("content") or obj.get("text") or obj.get("message"))
            if content:
                msg = Message.from_dict({
                    "role": "assistant",
                    "content": content,
                    "timestamp": obj.get("timestamp") or get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": obj.get("id") or obj.get("message_id") or generate_message_id(),
                    "model": obj.get("model") or self.model,
                    "provider": "gemini_cli",
                })
                messages.append(self._emit(msg))

        elif event_type == "tool_use":
            tool_call_id = obj.get("tool_id") or obj.get("id") or generate_message_id()
            tool_name = obj.get("tool_name") or obj.get("name") or obj.get("tool") or "tool"
            parameters = obj.get("parameters")
            if parameters is None:
                parameters = obj.get("input")
            if parameters is None:
                parameters = obj.get("arguments")
            if parameters is None:
                parameters = {}

            self._pending_tools[tool_call_id] = {"name": tool_name, "parameters": parameters}
            msg = Message.from_dict({
                "role": "assistant",
                "content": "",
                "timestamp": obj.get("timestamp") or get_utc_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": generate_message_id(),
                "model": obj.get("model") or self.model,
                "provider": "gemini_cli",
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

        elif event_type == "tool_result":
            tool_call_id = obj.get("tool_id") or obj.get("id") or obj.get("tool_call_id")
            tool_info = self._pending_tools.pop(tool_call_id, {}) if tool_call_id else {}
            tool_name = obj.get("tool_name") or obj.get("name") or tool_info.get("name")
            parameters = tool_info.get("parameters")
            content = obj.get("output")
            if content is None:
                content = obj.get("content")
            if content is None:
                content = obj.get("result")
            if obj.get("status") not in (None, "success", "completed"):
                suffix = f"[gemini tool status={obj.get('status')}]"
                text = _stringify(content).rstrip()
                content = f"{text}\n{suffix}" if text else suffix

            msg = Message.from_dict({
                "role": "tool",
                "content": _stringify(content),
                "timestamp": obj.get("timestamp") or get_utc_iso8601_timestamp(),
                "unix_timestamp": get_unix_timestamp(),
                "id": generate_message_id(),
                "tool": tool_name,
                "arguments": parameters,
                "tool_call_id": tool_call_id,
            })
            messages.append(self._emit(msg))

        elif event_type == "result":
            if obj.get("session_id") or obj.get("sessionId"):
                self.session_id = obj.get("session_id") or obj.get("sessionId")
            usage = _usage_from_stats(obj.get("stats", {}))
            if usage:
                self.usage = usage

        elif event_type == "error":
            logger.warning("gemini_cli error event: {}", obj.get("message") or obj.get("error") or obj)
        else:
            logger.debug("gemini_cli unknown event type: {}", event_type)

        return messages


def _gemini_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `<gemini cmd...> -p <prompt>`."""
    if images:
        image_lines = "\n".join(f"- {image_path}" for image_path in images)
        suffix = f"Attached image file path(s):\n{image_lines}"
        prompt = f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix
    full_cmd = list(cmd) + ["-p", prompt]
    return " ".join(_shell_quote(c) for c in full_cmd)


def _gemini_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") in ("init", "result"):
        return obj.get("session_id") or obj.get("sessionId") or obj.get("id")
    return None


def _gemini_spec() -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec
    return DetachBackendSpec(
        build_exec=_gemini_build_exec,
        parse_initial=_gemini_parse_initial,
    )


async def start_detached_gemini_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    ssh_client=None,
) -> Optional[str]:
    """Start Gemini CLI in a detached tmux session on the remote host."""
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        vm_config=vm_config,
        spec=_gemini_spec(),
        env=env,
        images=images,
        ssh_client=ssh_client,
    )


async def tail_gemini_output(
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
    """Tail a detached Gemini CLI process's stdout file via SSH."""
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

    converter = GeminiStreamConverter(last_message_id=last_message_id)
    result_data = None
    last_error_data = None
    current_offset = offset
    steer_msgs = []
    steer_requested = False

    try:
        tail_cmd = (
            f"tail -n +{offset + 1} -f {_shell_quote(stdout_file)} & TAIL_PID=$!; "
            f"(while ! test -f {_shell_quote(exit_file)}; do sleep 2; done; "
            f"sleep 1; kill $TAIL_PID 2>/dev/null) & "
            f"wait $TAIL_PID 2>/dev/null"
        )
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        def _kill_detached():
            logger.info("interrupt watchdog (gemini detached): killing tmux session cc-{}", chat_id)
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
            logger.info("steer (gemini detached): killing tmux session cc-{} to resume", chat_id)
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
            nonlocal result_data, last_error_data, current_offset
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
                            client.exec_command(f"pkill -f 'tail.*cc-{chat_id}.stdout' 2>/dev/null")
                        except Exception:
                            pass
                        stdout_ch.channel.close()
                        return "deadline"

                    obj = parse_stream_line(line)
                    if not obj:
                        continue

                    evt = obj.get("type")
                    if evt == "result":
                        result_data = obj
                        converter.process_line(line)
                        continue
                    if evt == "error":
                        last_error_data = {
                            "is_error": True,
                            "result": _stringify(obj.get("message") or obj.get("error") or obj),
                        }
                        converter.process_line(line)
                        continue

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
            logger.info("tail_gemini_output cancelled: chat_id={} offset={}", chat_id, current_offset)
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
        if result_data and result_data.get("status") not in (None, "success", "completed"):
            status = "error"
            result_data = {
                **result_data,
                "is_error": True,
                "result": (
                    result_data.get("error")
                    or result_data.get("message")
                    or (last_error_data.get("result") if last_error_data else None)
                    or "Gemini CLI exited with an error."
                ),
            }
        elif result_data is None:
            logger.warning(
                "tail_gemini_output: chat_id={} exited with no result event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            result_data = {
                "is_error": True,
                "result": (
                    (last_error_data.get("result") if last_error_data else None)
                    or "Gemini CLI exited before producing a result event."
                ),
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
        logger.error("tail_gemini_output error: {} {}", type(e).__name__, e)
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
