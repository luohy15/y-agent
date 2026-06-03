"""Convert pi (pi.dev coding agent) json-mode events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

pi (`pi -p --mode json "<prompt>"`) emits newline-delimited JSON events. The
relevant types are:
  - session              : first line, carries the session id (`id`) + cwd
  - message_start/_update/_end : streaming message chunks (user + assistant)
  - tool_execution_start : tool call request (toolCallId, toolName, args)
  - tool_execution_end   : tool output (result.content, isError)
  - agent_end            : terminal event, carries the full messages[]

There is no dedicated "result" summary or top-level "error" event: completion
is signalled by `agent_end`, token usage lives per assistant message, and
failures surface as a process exit without `agent_end`. This mirrors the
gemini_cli backend's "exited before producing a result event" fallback.
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional

from loguru import logger

from storage.entity.dto import Message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from agent.claude_code import parse_stream_line, _parse_ssh_target, _shell_quote, _ssh_exec
from agent.poll_loop import PollLoop


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


class PiStreamConverter:
    """Stateful JSONL event converter that maps pi json-mode events to y-agent messages."""

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

    def _accumulate_usage(self, usage) -> None:
        if not isinstance(usage, dict):
            return
        # pi reports per-message usage as {input, output, ...}. input_tokens is the
        # turn's full context (last-wins); output_tokens is generated (summed).
        input_tokens = usage.get("input")
        output_tokens = usage.get("output")
        if input_tokens is not None:
            self.usage["input_tokens"] = int(input_tokens)
        if output_tokens is not None:
            self.usage["output_tokens"] = self.usage.get("output_tokens", 0) + int(output_tokens)

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
            self._accumulate_usage(message.get("usage"))
            self.model = message.get("model") or self.model
            content = _assistant_text(message.get("content"))
            if content:
                msg = Message.from_dict({
                    "role": "assistant",
                    "content": content,
                    "timestamp": get_utc_iso8601_timestamp(),
                    "unix_timestamp": get_unix_timestamp(),
                    "id": generate_message_id(),
                    "model": message.get("model") or self.model,
                    "provider": "pi_cli",
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
                "provider": "pi_cli",
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
            # Terminal event; usage was accumulated from message_end events.
            pass
        else:
            logger.debug("pi_cli unhandled event type: {}", event_type)

        return messages


def _pi_build_exec(cmd: List[str], chat_id: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """Build `<pi cmd...> <prompt>` (pi takes the prompt as a positional message)."""
    if images:
        image_lines = "\n".join(f"- {image_path}" for image_path in images)
        suffix = f"Attached image file path(s):\n{image_lines}"
        prompt = f"{prompt.rstrip()}\n\n{suffix}" if prompt.strip() else suffix
    full_cmd = list(cmd) + [prompt]
    return " ".join(_shell_quote(c) for c in full_cmd)


def _pi_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "session":
        return obj.get("id")
    return None


def _write_pi_models_json(client, models_provider: Dict[str, dict]) -> None:
    """Merge custom provider entries into ~/.pi/agent/models.json on the remote host.

    pi reads custom providers (gateways, proxies, self-hosted models) from
    $PI_CODING_AGENT_DIR/models.json (default ~/.pi/agent/models.json). The merge
    is keyed by provider name so multiple bots and any hand-written entries
    coexist; only the providers we own are overwritten on each launch.
    """
    home = _ssh_exec(client, 'printf %s "$HOME"').strip()
    agent_dir = f"{home}/.pi/agent"
    models_path = f"{agent_dir}/models.json"
    _ssh_exec(client, f"mkdir -p {_shell_quote(agent_dir)}")

    # `|| true` keeps a missing file from surfacing cat's exit-1 (which _ssh_exec
    # would otherwise raise on, since 2>/dev/null only suppresses stderr text).
    existing = _ssh_exec(client, f"cat {_shell_quote(models_path)} 2>/dev/null || true").strip()
    data = {}
    if existing:
        try:
            data = json.loads(existing)
        except (ValueError, TypeError):
            logger.warning("pi_cli: ignoring unparseable models.json on remote host")
            data = {}
    if not isinstance(data, dict):
        data = {}

    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers
    providers.update(models_provider)

    payload = json.dumps(data, indent=2)
    sftp = client.open_sftp()
    try:
        with sftp.open(models_path, "w") as handle:
            handle.write(payload)
    finally:
        sftp.close()

    # The file holds a plaintext api key, so keep it owner-only.
    _ssh_exec(client, f"chmod 600 {_shell_quote(models_path)}")


def _pi_spec(models_provider: Optional[Dict[str, dict]] = None) -> "DetachBackendSpec":
    from agent.detach import DetachBackendSpec

    setup = None
    if models_provider:
        def setup(client, chat_id, prompt, images, _provider=models_provider):
            _write_pi_models_json(client, _provider)

    return DetachBackendSpec(
        build_exec=_pi_build_exec,
        parse_initial=_pi_parse_initial,
        setup=setup,
    )


async def start_detached_pi_ssh(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config: "VmConfig",
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    models_provider: Optional[Dict[str, dict]] = None,
    ssh_client=None,
) -> Optional[str]:
    """Start pi in a detached tmux session on the remote host.

    When `models_provider` is set (bot_config.base_url is configured), a custom
    provider is merged into the remote ~/.pi/agent/models.json before launch.
    """
    from agent.detach import _start_detached_tmux
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        vm_config=vm_config,
        spec=_pi_spec(models_provider),
        env=env,
        images=images,
        ssh_client=ssh_client,
    )


async def tail_pi_output(
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
    """Tail a detached pi process's stdout file via SSH."""
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

    converter = PiStreamConverter(last_message_id=last_message_id)
    result_data = None
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
            logger.info("interrupt watchdog (pi detached): killing tmux session cc-{}", chat_id)
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
            logger.info("steer (pi detached): killing tmux session cc-{} to resume", chat_id)
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
            nonlocal result_data, current_offset
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

                    if obj.get("type") == "agent_end":
                        result_data = {"is_error": False}
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
            logger.info("tail_pi_output cancelled: chat_id={} offset={}", chat_id, current_offset)
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
        if result_data is None:
            logger.warning(
                "tail_pi_output: chat_id={} exited with no agent_end event (offset={})",
                chat_id, current_offset,
            )
            status = "error"
            result_data = {
                "is_error": True,
                "result": "pi exited before producing an agent_end event.",
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
        logger.error("tail_pi_output error: {} {}", type(e).__name__, e)
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
