"""Convert OpenAI Codex CLI JSONL events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Codex `codex exec --json` emits JSONL events:
  - thread.started  : thread_id
  - turn.started    : new turn begins
  - item.started    : tool/message item begins
  - item.completed  : tool/message item finishes
  - turn.completed  : usage stats; the launch input group completes here
  - turn.failed     : fatal turn error
  - error           : transient retry notice; fatal only if the turn never completes

`item.completed` of `type=error` (unknown model metadata) is ignored. It is
not a failed turn. `codex exec` has no live input channel: a mid-run message
ends the current turn (the tmux session is killed) and the locked closeout
relaunches the same thread with that message as the next prompt.
"""

import asyncio
import copy
import io
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
    _ssh_exec,
    _tmux_session_alive,
    _kill_session_marking_self_killed,
    _consume_self_kill_sentinel,
    _pkill_tail_cmd,
    _build_tail_cmd,
)
from agent.input_ledger import InputLedger
from agent.poll_loop import PollLoop

from agent.startup_diagnostic import (
    DIAGNOSTIC_DISPLAY_BYTES as DIAGNOSTIC_DISPLAY_BYTES,
    interpret_exit_file as interpret_exit_file, _strip_controls,
    format_startup_diagnostic, read_attempt_diagnostic,
)

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


CODEX_ARCHIVE_ROOT = "/Users/roy/luohy15/lifelog/sessions/codex/sessions"
CODEX_CONTINUITY_NOTE = (
    "Codex refused the recorded thread (no rollout found for it). "
    "The transcript is kept, but that native thread cannot continue. "
    "This turn starts a fresh Codex session."
)

_MISSING_ROLLOUT_LINE = re.compile(
    r"^Error:\s+thread/resume:\s+thread/resume failed:\s+no rollout found for thread id\s+"
    r"([0-9a-fA-F-]{36})\s+\(code\s+-32600\)\s*$"
)


def format_codex_startup_diagnostic(stderr, exit_raw=None, **kwargs):
    return format_startup_diagnostic(stderr, exit_raw, backend="Codex", **kwargs)


def read_codex_attempt_diagnostic(client, chat_id, stream_error=None):
    return read_attempt_diagnostic(client, chat_id, stream_error, backend="Codex")


def codex_missing_rollout_id(stderr: Optional[str], attempted_id: Optional[str]) -> Optional[str]:
    """Return ``attempted_id`` only when this attempt's stderr is the native refusal.

    The match is one CLI error line, not assistant prose that quotes the phrase,
    and the thread id in that line must be the id this attempt resumed.
    """
    if not isinstance(stderr, str) or not isinstance(attempted_id, str) or not attempted_id:
        return None
    for line in _strip_controls(stderr).splitlines():
        match = _MISSING_ROLLOUT_LINE.match(line.strip())
        if match and match.group(1) == attempted_id:
            return attempted_id
    return None


def codex_refusal_authorizes_recovery(
    *,
    stderr: Optional[str],
    attempted_id: Optional[str],
    exit_code: Optional[int],
    has_usable_output: bool = False,
) -> bool:
    """True only for the native missing-rollout signal of the attempted id.

    Exit 1 is required and not sufficient. Usable stdout, any other exit
    (including 137 and 143), and a line that names a different id are rejected.
    """
    if has_usable_output or exit_code != 1:
        return False
    return codex_missing_rollout_id(stderr, attempted_id) == attempted_id


def codex_retry_decision(
    *,
    stderr: Optional[str],
    attempted_id: Optional[str],
    exit_code: Optional[int],
    has_usable_output: bool = False,
    retries: int = 0,
    interrupted: bool = False,
    stale_run: bool = False,
) -> str:
    """``retry``, ``ceiling``, ``blocked``, or ``no-retry``. Does not launch anything."""
    if interrupted or stale_run:
        return "blocked"
    if not codex_refusal_authorizes_recovery(
        stderr=stderr,
        attempted_id=attempted_id,
        exit_code=exit_code,
        has_usable_output=has_usable_output,
    ):
        return "no-retry"
    if int(retries or 0) >= 1:
        return "ceiling"
    return "retry"


def clear_refused_thread_id(current_id, refused_id, attempted_id) -> tuple:
    """Return ``(new_id, cleared)``. Only the exact current refused id is cleared."""
    if current_id and refused_id and attempted_id and current_id == refused_id == attempted_id:
        return None, True
    return current_id, False


CODEX_TURN_FAILURE_PREFIX = "Codex turn failed: "


def format_codex_turn_failure(message: Optional[str]) -> str:
    """One bounded diagnostic that cannot be read as model output."""
    text = message.strip() if isinstance(message, str) else ""
    if not text:
        text = "Unknown error"
    if not text.startswith("Codex "):
        text = f"{CODEX_TURN_FAILURE_PREFIX}{text}"
    raw = text.encode("utf-8")
    if len(raw) <= DIAGNOSTIC_DISPLAY_BYTES:
        return text
    return raw[:DIAGNOSTIC_DISPLAY_BYTES].decode("utf-8", errors="ignore")


def _codex_failure_data(message: Optional[str]) -> Dict:
    return {"is_error": True, "result": format_codex_turn_failure(message)}


def reduce_codex_turn_events(events) -> Dict:
    """Fold Codex protocol events into completion, fatal, and transient latches.

    `turn.completed` clears a transient `error` notice. It does not clear
    `turn.failed`. A later `error` can latch again.
    """
    completed = None
    fatal = None
    transient = None
    for obj in events or []:
        if not isinstance(obj, dict):
            continue
        event_type = obj.get("type")
        if event_type == "turn.completed":
            completed = obj
            transient = None
        elif event_type == "turn.failed":
            error = obj.get("error") or {}
            fatal = _codex_failure_data(error.get("message") or "Turn failed")
        elif event_type == "error":
            transient = _codex_failure_data(obj.get("message") or "Unknown error")
    return {"completed": completed, "fatal": fatal, "transient": transient}


def codex_turn_status(events, *, steered: bool = False, exit_reason: Optional[str] = None) -> str:
    """End-of-turn status from protocol events. No SSH and no process probe.

    `interrupted` and `deadline` win. `turn.failed` is always fatal. A
    transient `error` does not fail a later `turn.completed` and does not
    block a steer. An `error` that is still latched (no completion, or an
    error after completion) is fatal unless the turn was steered.
    `pending` means the caller still has to look at the process.
    """
    reduced = reduce_codex_turn_events(events)
    if exit_reason == "interrupted":
        return "interrupted"
    if exit_reason == "deadline":
        return "monitoring"
    if reduced["fatal"] is not None:
        return "error"
    # A transient notice still present was not cleared by turn.completed.
    # Steer treats that notice as compatible with a completed turn; anything
    # else, including an error after completion, is fatal.
    if reduced["transient"] is not None and not steered:
        return "error"
    if reduced["completed"] is not None or steered:
        return "completed"
    return "pending"


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


def normalize_usage(usage) -> dict:
    """Turn counters in the shared, cache-exclusive input convention.

    Missing or malformed counters stay unknown. Reasoning is already included
    in output; adding it again would overcount.
    """
    usage = usage if isinstance(usage, dict) else {}

    def counter(name):
        value = usage.get(name)
        return value if type(value) is int and 0 <= value <= 2_147_483_647 else None

    raw_input = counter("input_tokens")
    cached = counter("cached_input_tokens")
    result = {
        "input_tokens": raw_input - cached if raw_input is not None and cached is not None and cached <= raw_input else None,
        "output_tokens": counter("output_tokens"),
        "cache_creation_tokens": counter("cache_write_input_tokens"),
        "cache_read_tokens": cached if raw_input is None or cached is None or cached <= raw_input else None,
    }
    result["usage_state"] = "observed" if any(value is not None for value in result.values()) else "missing"
    return result


_THREAD_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ROLLOUT_TAIL_BYTES = 262144


def _collect_rollout_fields(obj, found: dict) -> None:
    """Last complete `model_context_window` and `last_token_usage` win."""
    if isinstance(obj, dict):
        window = obj.get("model_context_window")
        if type(window) is int and 0 < window <= 2_147_483_647:
            found["context_window"] = window
        usage = obj.get("last_token_usage")
        if isinstance(usage, dict):
            normalized = normalize_usage(usage)
            if normalized.get("usage_state") == "observed":
                found["request_usage"] = normalized
        for value in obj.values():
            _collect_rollout_fields(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_rollout_fields(item, found)


def parse_codex_rollout_tail(text) -> dict:
    """Window and final-request usage from a bounded Codex rollout tail.

    A line that is not complete JSON is ignored, so a `tail -c` cut at the
    start does not invent a window. Missing keys stay None.
    """
    found = {"context_window": None, "request_usage": None}
    if not isinstance(text, str) or not text:
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        _collect_rollout_fields(obj, found)
    return found


def read_codex_rollout(client, thread_id: str):
    """Read the node's rollout tail for this thread, or None on any failure.

    The thread id must be a hyphenated UUID. Anything else returns None without
    a remote call. The remote read is `tail -c` of one session file.
    """
    if client is None or not isinstance(thread_id, str) or _THREAD_ID_RE.fullmatch(thread_id) is None:
        return None
    pattern = _shell_quote(f"*-{thread_id}.jsonl")
    cmd = (
        "f=$(find \"${CODEX_HOME:-$HOME/.codex}/sessions\" -name "
        f"{pattern} -print -quit); "
        f'[ -n "$f" ] && tail -c {_ROLLOUT_TAIL_BYTES} "$f"'
    )
    try:
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=20)
        raw = stdout.read()
        stderr.read()
        stdout.channel.recv_exit_status()
    except Exception:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw:
        return None
    return parse_codex_rollout_tail(raw)


class CodexStreamConverter:
    """Stateful JSONL event converter that maps Codex events to y-agent Messages."""

    def __init__(self, last_message_id: Optional[str] = None, model: Optional[str] = None):
        self.last_message_id = last_message_id
        self.model = model
        self.thread_id: Optional[str] = None
        self.usage = normalize_usage(None)
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
                    "model": self.model,
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
                    "model": self.model,
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
                        "model": self.model,
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
            self.usage = normalize_usage(obj.get("usage"))

        elif event_type == "turn.failed":
            error = obj.get("error", {})
            error_msg = error.get("message", "Turn failed")
            logger.error("codex turn.failed: {}", error_msg)

        elif event_type == "error":
            error_msg = obj.get("message", "Unknown error")
            logger.error("codex error event: {}", error_msg)

        return messages


# Codex resolves model metadata from its bundled catalog and falls back to
# 272,000 / 95% for slugs it does not know, so a 1M-context relay model would
# report 258,400 usable tokens and compact early. A per-launch
# `model_catalog_json` is the only lever that raises both the reported window
# and the auto-compaction threshold.
_CODEX_GENERIC_TEMPLATE_SLUG = "gpt-5.2"
_CODEX_NEUTRAL_IDENTITY = "You are a coding agent running in the Codex CLI"
_CODEX_IDENTITY_RE = re.compile(r"^You are [^\n]*? running in the Codex CLI")


def _bundled_model_entries(bundled) -> List[Dict]:
    models = bundled.get("models") if isinstance(bundled, dict) else None
    if not isinstance(models, list):
        return []
    return [
        entry for entry in models
        if isinstance(entry, dict) and isinstance(entry.get("slug"), str) and entry["slug"]
    ]


def _longest_prefix_entry(model: str, entries: List[Dict]) -> Optional[Dict]:
    """Codex's bundled lookup: the longest catalog slug that prefixes the model."""
    best = None
    for entry in entries:
        if not model.startswith(entry["slug"]):
            continue
        if best is None or len(entry["slug"]) > len(best["slug"]):
            best = entry
    return best


def _namespaced_suffix(model: str) -> Optional[str]:
    """One leading provider segment, matching Codex's narrow namespaced retry."""
    namespace, sep, suffix = model.partition("/")
    if not sep or not namespace or not suffix or "/" in suffix:
        return None
    if not all(
        ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9") or char in "_-"
        for char in namespace
    ):
        return None
    return suffix


def _resolve_bundled_entry(model: str, entries: List[Dict]) -> Optional[Dict]:
    found = _longest_prefix_entry(model, entries)
    if found is not None:
        return found
    suffix = _namespaced_suffix(model)
    return _longest_prefix_entry(suffix, entries) if suffix else None


def _neutralize_identity(text) -> str:
    """Replace a bundled model's first-line identity with the CLI fallback one."""
    if not isinstance(text, str):
        return text
    first, sep, rest = text.partition("\n")
    first, count = _CODEX_IDENTITY_RE.subn(_CODEX_NEUTRAL_IDENTITY, first, count=1)
    return first + sep + rest if count else text


def build_codex_model_catalog(bundled, model, window):
    """Build a full Codex catalog whose entry for ``model`` reports ``window``.

    ``bundled`` is the parsed `codex debug models --bundled` payload. A bundled
    entry for the model (exact, longest prefix, or one namespaced suffix) is
    cloned, so its tools and prompt stay intact. A CLI-unknown slug clones the
    generic gpt-5.2 template with its identity neutralized and `comp_hash`
    cleared. `window` becomes both the report and the hard cap, with 100%
    effective so the reported window is the real one; Codex still starts
    auto-compaction at 90%. Returns ``None`` when there is nothing to build.
    """
    if not isinstance(model, str) or not model.strip():
        return None
    if isinstance(window, bool) or not isinstance(window, int) or not 0 < window <= 2_147_483_647:
        return None
    model = model.strip()
    entries = _bundled_model_entries(bundled)
    if not entries:
        return None

    source = _resolve_bundled_entry(model, entries)
    template = source is None
    if template:
        source = next(
            (entry for entry in entries if entry["slug"] == _CODEX_GENERIC_TEMPLATE_SLUG), None,
        )
    if source is None:
        return None

    entry = copy.deepcopy(source)
    entry["slug"] = model
    entry["display_name"] = model
    entry["context_window"] = window
    entry["max_context_window"] = window
    entry["auto_compact_token_limit"] = None
    entry["effective_context_window_percent"] = 100
    if template:
        entry["comp_hash"] = None
        messages = entry.get("model_messages")
        if isinstance(messages, dict) and isinstance(messages.get("instructions_template"), str):
            messages["instructions_template"] = _neutralize_identity(
                messages["instructions_template"]
            )
        if isinstance(entry.get("base_instructions"), str):
            entry["base_instructions"] = _neutralize_identity(entry["base_instructions"])

    models = [item for item in bundled["models"] if isinstance(item, dict) and item.get("slug") != model]
    models.append(entry)
    catalog = dict(bundled)
    catalog["models"] = models
    return catalog


def _dump_bundled_catalog(client, cmd: List[str], node) -> Optional[Dict]:
    """Read the node's bundled catalog with the same binary and PATH as the launch."""
    binary = cmd[0] if cmd else "codex"
    prefix = f"env PATH={_shell_quote(node.path)} " if getattr(node, "path", None) else ""
    raw = _ssh_exec(client, f"{prefix}{_shell_quote(binary)} debug models --bundled")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else None


def _catalog_from_node(client, cmd, node, model, window) -> Optional[Dict]:
    """Best-effort launch catalog. Any dump or parse failure keeps the launch as-is."""
    try:
        bundled = _dump_bundled_catalog(client, cmd, node)
        if bundled is None:
            logger.warning("codex bundled catalog dump returned no catalog model={}", model)
            return None
        catalog = build_codex_model_catalog(bundled, model, window)
    except Exception as exc:
        logger.warning(
            "codex bundled catalog dump failed model={} error={}", model, type(exc).__name__,
        )
        return None
    if catalog is None:
        logger.warning("codex model catalog not built model={} window={}", model, window)
    return catalog


def _stage_model_catalog(client, cmd: List[str], chat_id: str, catalog_text: str) -> None:
    """Write the catalog on the node and only then point Codex at it."""
    from agent.detach import model_catalog_path

    path = model_catalog_path(chat_id)
    try:
        sftp = client.open_sftp()
        try:
            sftp.putfo(io.BytesIO(catalog_text.encode("utf-8")), path)
        finally:
            sftp.close()
    except Exception as exc:
        logger.warning(
            "codex model catalog staging failed chat_id={} error={}", chat_id, type(exc).__name__,
        )
        return
    cmd.extend(["-c", f'model_catalog_json="{path}"'])


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
    exec_cmd = f"{quoted} < /dev/null"
    if len(cmd) < 4 or cmd[1:3] != ["exec", "resume"] or not _THREAD_ID_RE.fullmatch(cmd[3]):
        return exec_cmd

    # The default node's backup preserves the rollout's YYYY/MM/DD path.
    # Nodes without that archive no-op; isolated launches retain their CODEX_HOME.
    restore_snippet = (
        f"_y_archive={_shell_quote(CODEX_ARCHIVE_ROOT)}; "
        f"_y_src=$(find \"$_y_archive\" -type f -name {_shell_quote('*-' + cmd[3] + '.jsonl')} "
        "-print -quit 2>/dev/null); "
        "if [ -s \"$_y_src\" ]; then "
        "_y_rel=${_y_src#\"$_y_archive\"/}; "
        "_y_dst=\"${CODEX_HOME:-$HOME/.codex}/sessions/$_y_rel\"; "
        "if [ ! -f \"$_y_dst\" ]; then "
        "mkdir -p \"$(dirname \"$_y_dst\")\" && cp -p \"$_y_src\" \"$_y_dst\"; "
        "fi; fi; "
    )
    # Keep restore and launch together behind the outer `cd <cwd> &&` guard.
    return "( " + restore_snippet + exec_cmd + " )"


def _codex_parse_initial(obj: Dict) -> Optional[str]:
    if obj.get("type") == "thread.started":
        return obj.get("thread_id")
    return None


def _codex_spec(model_catalog: Optional[Tuple[List[str], str]] = None) -> "DetachBackendSpec":
    """Codex launch hooks. ``model_catalog`` is ``(cmd, catalog_json_text)``.

    The catalog is staged after the attempt-log reset, and the ``-c`` flag is
    appended only once the file exists, so a staging failure launches unchanged.
    """
    from agent.detach import DetachBackendSpec
    setup = None
    if model_catalog is not None:
        catalog_cmd, catalog_text = model_catalog

        def setup(client, chat_id, prompt, images):
            _stage_model_catalog(client, catalog_cmd, chat_id, catalog_text)
    return DetachBackendSpec(
        build_exec=_codex_build_exec,
        parse_initial=_codex_parse_initial,
        setup=setup,
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
    model: Optional[str] = None,
    context_window: Optional[int] = None,
) -> Optional[str]:
    """Start `codex exec` in a detached tmux session on the chat's node.

    Codex takes the prompt as a positional argument and does not read
    stream-json stdin. stdout / stderr / exit files use `/tmp/cc-<chat_id>.*`.
    When the model has a known context window, the node's bundled catalog is
    cloned into a per-launch catalog so Codex reports and uses that window.

    Returns the thread_id from the initial `thread.started` event, else None.
    """
    from agent.detach import _start_detached_tmux, _with_ssh_client

    spec = _codex_spec()
    build_catalog = bool(model) and bool(context_window)
    if build_catalog:
        with _with_ssh_client(node, ssh_client) as client:
            catalog = _catalog_from_node(client, cmd, node, model, context_window)
            if catalog is not None:
                spec = _codex_spec((cmd, json.dumps(catalog)))
            return await _start_detached_tmux(
                cmd=cmd,
                prompt=prompt,
                cwd=cwd,
                chat_id=chat_id,
                node=node,
                spec=spec,
                env=env,
                images=images,
                ssh_client=client,
                unset_env=unset_env,
            )
    return await _start_detached_tmux(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        chat_id=chat_id,
        node=node,
        spec=spec,
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
    resume_thread_id: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Tail a detached codex process's stdout file via SSH.

    `check_steer_fn` supplies messages accepted mid-run. `codex exec` has no
    live input channel, so a steer ends the turn: the session is killed, the
    launch input group is retired, and the message stays pending for the
    closeout continuation, which resumes the same thread with it. Interrupt
    keeps priority. `turn.completed` marks the launch input group completed;
    otherwise anything that arrived during the run stays outstanding.

    Fatal on `turn.failed`, on a top-level `error` that no later
    `turn.completed` clears, or on a session that exits without
    `turn.completed`. A cleared retry notice is not fatal and does not block
    steer. A self-kill for steer or interrupt is not a death.
    """
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = CodexStreamConverter(last_message_id=last_message_id, model=model)
    ledger = input_ledger if input_ledger is not None else InputLedger(chat_id)
    result_data = pending_result if isinstance(pending_result, dict) else None
    if result_data and result_data.get("type") == "turn.completed" and not result_data.get("is_error"):
        _complete_launch_group(ledger, launch_input_uuid)
        converter.usage = normalize_usage(result_data.get("usage"))
    turn_events = []
    if isinstance(result_data, dict) and result_data.get("type") == "turn.completed":
        turn_events.append(result_data)
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
            "usage": converter.usage,
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
            nonlocal result_data, current_offset, stream_error, torn_down
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
                        turn_events.append(obj)
                        with steer_lock:
                            _complete_launch_group(ledger, launch_input_uuid)
                        converter.process_line(line)
                        continue

                    if evt == "turn.failed":
                        turn_events.append(obj)
                        converter.process_line(line)
                        continue
                    if evt == "error":
                        turn_events.append(obj)
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

        reduced = reduce_codex_turn_events(turn_events)
        decision = codex_turn_status(
            turn_events,
            steered=steered.is_set(),
            exit_reason=exit_reason,
        )
        if decision == "completed" and reduced["completed"] is None and exit_reason != "interrupted":
            # Our own steer kill ended the turn before it completed. A transient
            # retry notice does not block this. A fatal failure does not take
            # this branch. Consume the sentinel so no later check misreads it,
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
        no_result_attempt = None
        self_killed = False
        if decision == "pending" and exit_reason is None:
            self_killed = _consume_self_kill_sentinel(client, chat_id)
            if not self_killed:
                no_result_session_alive = _tmux_session_alive(client, chat_id, node=node)
                if not no_result_session_alive:
                    attempt = read_codex_attempt_diagnostic(client, chat_id, stream_error)
                    no_result_error = attempt["text"]
                    no_result_attempt = attempt

        if owns_client:
            from agent.chat_target import close_owned_client
            close_owned_client(client)

        if decision == "interrupted":
            return _view(True, "interrupted", None)

        if decision == "monitoring":
            return _view(False, "monitoring", reduced["completed"])

        status = "completed"
        data = reduced["completed"]
        if decision == "error":
            status = "error"
            data = reduced["fatal"] or reduced["transient"]
        elif reduced["completed"] is None:
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

        view = _view(True, status, data)
        if status == "error" and no_result_attempt is not None:
            exit_code = no_result_attempt.get("exit_code")
            stderr = no_result_attempt.get("stderr")
            refused = codex_refusal_authorizes_recovery(
                stderr=stderr,
                attempted_id=resume_thread_id,
                exit_code=exit_code,
                has_usable_output=converter.has_usable_output,
            )
            view["exit_code"] = exit_code
            view["attempt_stderr"] = stderr
            view["startup_diagnostic"] = no_result_attempt.get("text")
            view["resume_refused"] = refused
            view["refused_thread_id"] = resume_thread_id if refused else None
        return view

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
