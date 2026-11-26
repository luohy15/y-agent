"""Convert OpenAI Codex CLI events to y-agent Message DTOs,
and provide SSH helpers for detached tmux-based execution.

Two Codex harnesses share one transcript path. `codex exec --json` (the default)
emits JSONL events:
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

`Y_CODEX_HARNESS=app-server` instead runs one `codex app-server --listen
stdio://` per turn behind the same stdin pipe. Its v2 JSON-RPC notifications
are folded into the exec event shapes above, so the converter, usage rows and
rollout closeout stay unchanged, and `turn/steer` delivers a mid-turn message
without ending the turn (todo 4476).
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
from agent.input_ledger import InputLedger, native_input_uuid
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
    """Window, final-request usage and that request's own time from a bounded tail.

    A line that is not complete JSON is ignored, so a `tail -c` cut at the
    start does not invent a window. Missing keys stay None. `usage_at` is the
    top-level `timestamp` of the line that supplied the winning
    `last_token_usage`, never the tail read time.
    """
    found = {"context_window": None, "request_usage": None, "usage_at": None}
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
        line_found = {"context_window": None, "request_usage": None}
        _collect_rollout_fields(obj, line_found)
        if line_found["context_window"] is not None:
            found["context_window"] = line_found["context_window"]
        if line_found["request_usage"] is not None:
            found["request_usage"] = line_found["request_usage"]
            stamp = obj.get("timestamp") if isinstance(obj, dict) else None
            found["usage_at"] = stamp if isinstance(stamp, str) and stamp else None
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
        return self.process_event(obj)

    def process_event(self, obj: Dict) -> List[Message]:
        """Map one parsed exec-shaped event to messages.

        The app-server harness folds its v2 notifications into these shapes, so
        both harnesses share this mapping.
        """
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
# Prefer the historical generic slug, then gpt-5.5 (present in 0.153 and 0.172).
# Anything else except the review-only entry is a last resort. Exact, prefix,
# and namespaced bundled matches never use this list.
_CODEX_GENERIC_TEMPLATE_SLUGS = ("gpt-5.2", "gpt-5.5")
_CODEX_TEMPLATE_EXCLUDED_SLUGS = frozenset({"codex-auto-review"})
_CODEX_NEUTRAL_IDENTITY = "You are a coding agent running in the Codex CLI"
_CODEX_IDENTITY_RE = re.compile(r"^You are [^\n]*? running in the Codex CLI")
# 0.172 entries use a sentence, not the historical CLI prefix. The version may
# contain dots (GPT-5.5); the sentence period is the one after that version.
_CODEX_MODEL_IDENTITY_RE = re.compile(
    r"^You are Codex, [^.\n]* based on GPT-\d+(?:\.\d+)*\."
)


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


def _generic_template_entry(entries: List[Dict]) -> Optional[Dict]:
    """Template for a slug Codex does not know. Never replaces a resolved entry."""
    by_slug = {}
    for entry in entries:
        by_slug.setdefault(entry["slug"], entry)
    for slug in _CODEX_GENERIC_TEMPLATE_SLUGS:
        found = by_slug.get(slug)
        if found is not None:
            return found
    for entry in entries:
        if entry["slug"] not in _CODEX_TEMPLATE_EXCLUDED_SLUGS:
            return entry
    return None


def _neutralize_identity(text) -> str:
    """Replace a bundled model's first-line identity with the CLI fallback one.

    Keeps the remainder of the line. The historical form ends at
    ``running in the Codex CLI``; a 0.172 ``You are Codex, ... based on GPT-N.``
    sentence is replaced with the same identity plus its sentence period.
    """
    if not isinstance(text, str):
        return text
    first, sep, rest = text.partition("\n")
    updated, count = _CODEX_IDENTITY_RE.subn(_CODEX_NEUTRAL_IDENTITY, first, count=1)
    if not count:
        updated, count = _CODEX_MODEL_IDENTITY_RE.subn(
            _CODEX_NEUTRAL_IDENTITY + ".", first, count=1,
        )
    return updated + sep + rest if count else text


def build_codex_model_catalog(bundled, model, window):
    """Build a full Codex catalog whose entry for ``model`` reports ``window``.

    ``bundled`` is the parsed `codex debug models --bundled` payload. A bundled
    entry for the model (exact, longest prefix, or one namespaced suffix) is
    cloned, so its tools and prompt stay intact. A CLI-unknown slug clones the
    first generic template that exists (`gpt-5.2`, then `gpt-5.5`, otherwise
    the first bundled entry other than `codex-auto-review`), with its identity
    neutralized and `comp_hash` cleared. `window` becomes both the report and
    the hard cap, with 100% effective so the reported window is the real one;
    Codex still starts auto-compaction at 90%. Returns ``None`` when there is
    nothing to build.
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
        source = _generic_template_entry(entries)
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


def _codex_restore_archive_cmd(thread_id: str) -> str:
    """Best-effort restore of a resumed thread's rollout from the node backup.

    The default node's backup preserves the rollout's YYYY/MM/DD path. Nodes
    without that archive no-op; isolated launches retain their CODEX_HOME.
    """
    return (
        f"_y_archive={_shell_quote(CODEX_ARCHIVE_ROOT)}; "
        f"_y_src=$(find \"$_y_archive\" -type f -name {_shell_quote('*-' + thread_id + '.jsonl')} "
        "-print -quit 2>/dev/null); "
        "if [ -s \"$_y_src\" ]; then "
        "_y_rel=${_y_src#\"$_y_archive\"/}; "
        "_y_dst=\"${CODEX_HOME:-$HOME/.codex}/sessions/$_y_rel\"; "
        "if [ ! -f \"$_y_dst\" ]; then "
        "mkdir -p \"$(dirname \"$_y_dst\")\" && cp -p \"$_y_src\" \"$_y_dst\"; "
        "fi; fi"
    )


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

    # Keep restore and launch together behind the outer `cd <cwd> &&` guard.
    return "( " + _codex_restore_archive_cmd(cmd[3]) + "; " + exec_cmd + " )"


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


# ---------------------------------------------------------------------------
# App-server harness (todo 4476): `Y_CODEX_HARNESS=app-server`
# ---------------------------------------------------------------------------

CODEX_APP_SERVER_HARNESS = "app-server"
APP_SERVER_HOME_SUFFIX = ".codex-home"
APP_SERVER_PENDING_TYPE = "codex_app_server_pending"

# Per-process JSON-RPC ids. A steer's id is the input's native uuid, which is
# also the input ledger's group key, so its response correlates directly.
APP_INIT_ID = "y-agent-initialize"
APP_THREAD_ID = "y-agent-thread"
APP_TURN_ID = "y-agent-turn"
APP_TURNS_LIST_ID = "y-agent-turns-list"

# Streamed deltas are rebuilt from item/completed, so the connection opts out
# of the per-token streams.
APP_SERVER_OPT_OUT_METHODS = (
    "item/agentMessage/delta",
    "item/reasoning/summaryPartAdded",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/textDelta",
    "item/plan/delta",
    "item/commandExecution/outputDelta",
    "item/commandExecution/terminalInteraction",
    "item/fileChange/outputDelta",
    "item/fileChange/patchUpdated",
    "item/mcpToolCall/progress",
    "turn/diff/updated",
    "turn/plan/updated",
)

_APP_SERVER_CONFIG_TOML = """\
# Staged by y-agent for this launch. app-server has no --ignore-user-config,
# so a private CODEX_HOME is how the user's own config/hooks/MCP stay out.
# Same policy as `codex exec --dangerously-bypass-approvals-and-sandbox`.
approval_policy = "never"
sandbox_mode = "danger-full-access"
"""

APP_SERVER_NO_THREAD_ERROR = (
    "Codex app-server exited 0 before opening a thread and wrote no output. "
    "The initialize/thread response never arrived; check the node's codex "
    "startup and the staged CODEX_HOME."
)

_MISSING_ROLLOUT_MESSAGE_RE = re.compile(
    r"no rollout found for thread id\s+([0-9a-fA-F-]{36})"
)


def codex_app_server_config_text() -> str:
    return _APP_SERVER_CONFIG_TOML


def codex_app_server_home(chat_id: str) -> str:
    return f"/tmp/cc-{chat_id}{APP_SERVER_HOME_SUFFIX}"


def _salvage_app_server_home_cmd(chat_id: str) -> str:
    """Copy any retained home's rollouts to the resume source, failing loudly."""
    staged = _shell_quote(codex_app_server_home(chat_id) + "/sessions")
    return (
        f"_y_src={staged}; "
        "if [ -d \"$_y_src\" ] && find \"$_y_src\" -type f -name '*.jsonl' -print -quit | grep -q .; then "
        "_y_dst=\"${CODEX_HOME:-$HOME/.codex}/sessions\"; "
        "mkdir -p \"$_y_dst\" || exit 1; "
        "find \"$_y_src\" -type f -name '*.jsonl' -print | while IFS= read -r _y_f; do "
        "_y_rel=${_y_f#\"$_y_src\"/}; "
        "mkdir -p \"$_y_dst/$(dirname \"$_y_rel\")\" || exit 1; "
        "cp -p \"$_y_f\" \"$_y_dst/$_y_rel\" || exit 1; "
        "done || exit 1; "
        "fi"
    )


def _salvage_app_server_home(client, chat_id: str) -> None:
    """Publish a retained home's rollouts before the next launch wipes it.

    A hard timeout whose copy-out failed (destination unreadable, node
    pressure) leaves the previous attempt's home behind. The next same-chat
    launch must not delete that rollout before resume looks for it, so copy
    every rollout into the resume source first. A failed copy raises: staging
    aborts with the home intact instead of wiping the only copy.
    """
    _ssh_exec(client, _salvage_app_server_home_cmd(chat_id))


def _stage_app_server_home(client, chat_id: str) -> str:
    """Create this launch's CODEX_HOME: generated config + an empty sessions dir.

    The sessions directory must stay private to this launch. Pointing it at the
    real `$HOME/.codex/sessions` makes app-server backfill every rollout before
    it answers `initialize` (1,197 files and tens of seconds on the default
    node), which overran the launch's wait budget in the first soak. A resumed
    launch copies just its own thread's rollout in (`_stage_resume_rollout_cmd`)
    and the tail copies the result back (`_sync_app_server_rollouts_cmd`).
    No auth.json is staged: the relay credential comes from the provider's
    `env_key`.

    A home retained from a previous attempt (for example a hard timeout whose
    copy failed) is salvaged into the resume source before the wipe; if that
    salvage fails the wipe never happens.
    """
    home = codex_app_server_home(chat_id)
    _salvage_app_server_home(client, chat_id)
    _ssh_exec(
        client,
        f"rm -rf {_shell_quote(home)} && mkdir -p {_shell_quote(home + '/sessions')}",
    )
    sftp = client.open_sftp()
    try:
        with sftp.open(f"{home}/config.toml", "w") as handle:
            handle.write(_APP_SERVER_CONFIG_TOML)
    finally:
        sftp.close()
    return home


def _stage_resume_rollout_cmd(thread_id: str, codex_home: str) -> str:
    """Copy only the resumed thread's rollout into the staged home.

    The real `$HOME/.codex/sessions` is tried first, then the node's archive
    backup. The staged destination keeps the rollout's YYYY/MM/DD path, and
    app-server appends the new turn to that copy.
    """
    pattern = _shell_quote('*-' + thread_id + '.jsonl')
    dest_root = _shell_quote(codex_home.rstrip("/") + "/sessions")
    return (
        f"_y_root=\"${{CODEX_HOME:-$HOME/.codex}}/sessions\"; "
        f"_y_dst_root={dest_root}; "
        f"_y_f=$(find \"$_y_root\" -type f -name {pattern} -print -quit 2>/dev/null); "
        f"if [ -z \"$_y_f\" ]; then _y_root={_shell_quote(CODEX_ARCHIVE_ROOT)}; "
        f"_y_f=$(find \"$_y_root\" -type f -name {pattern} -print -quit 2>/dev/null); fi; "
        "if [ -s \"$_y_f\" ]; then _y_rel=${_y_f#\"$_y_root\"/}; "
        "mkdir -p \"$_y_dst_root/$(dirname \"$_y_rel\")\" && "
        "cp -p \"$_y_f\" \"$_y_dst_root/$_y_rel\"; fi"
    )


def _sync_app_server_rollouts_cmd(chat_id: str) -> str:
    """Copy every rollout in the staged home back to the real sessions tree."""
    staged = _shell_quote(codex_app_server_home(chat_id) + "/sessions")
    return (
        f"_y_src={staged}; _y_dst=\"${{CODEX_HOME:-$HOME/.codex}}/sessions\"; "
        "if [ -d \"$_y_src\" ]; then "
        "find \"$_y_src\" -type f -name '*.jsonl' -print | while IFS= read -r _y_f; do "
        "_y_rel=${_y_f#\"$_y_src\"/}; "
        "mkdir -p \"$_y_dst/$(dirname \"$_y_rel\")\" && cp -p \"$_y_f\" \"$_y_dst/$_y_rel\"; "
        "done; fi"
    )


def _remove_app_server_home(client, chat_id: str) -> None:
    """Remove the staged home once its rollout has been copied out."""
    try:
        _ssh_exec(client, f"rm -rf {_shell_quote(codex_app_server_home(chat_id))}")
    except Exception as exc:
        logger.warning("codex app-server home cleanup failed chat_id={}: {}", chat_id, exc)


def _sync_app_server_rollouts(client, chat_id: str) -> None:
    """Publish the staged rollouts where usage closeout and resume look for them.

    The tail removes the staged home after this copy, so the turn's rollout
    must reach `$HOME/.codex/sessions` before teardown completes. Best effort:
    a failure is logged and never fails the turn.
    """
    try:
        _ssh_exec(client, _sync_app_server_rollouts_cmd(chat_id))
    except Exception as exc:
        logger.warning("codex app-server rollout sync failed chat_id={}: {}", chat_id, exc)


def build_codex_app_server_launch(thread_id: Optional[str] = None, cwd: Optional[str] = None,
                                  model: Optional[str] = None) -> List[Dict]:
    """The JSONL commands written before launch: initialize + thread open.

    Two-phase: `turn/start` is appended only after the thread id is known
    (`DetachBackendSpec.after_initial`). `excludeTurns` keeps a resumed thread
    from loading and replaying its history.
    """
    params: Dict = {}
    if thread_id:
        params["threadId"] = thread_id
        params["excludeTurns"] = True
    if cwd:
        params["cwd"] = cwd
    if model:
        params["model"] = model
    method = "thread/resume" if thread_id else "thread/start"
    return [
        {
            "jsonrpc": "2.0", "id": APP_INIT_ID, "method": "initialize",
            "params": {
                "clientInfo": {"name": "y-agent", "version": "1"},
                "capabilities": {"optOutNotificationMethods": list(APP_SERVER_OPT_OUT_METHODS)},
            },
        },
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": APP_THREAD_ID, "method": method, "params": params},
    ]


def build_codex_app_server_turn(thread_id: str, prompt: str,
                                images: Optional[List[str]] = None,
                                input_uuid: Optional[str] = None) -> Dict:
    """`turn/start` for the launch input; images travel as localImage parts."""
    inputs: List[Dict] = [{"type": "text", "text": prompt}]
    for path in images or []:
        inputs.append({"type": "localImage", "path": path})
    params: Dict = {"threadId": thread_id, "input": inputs}
    if input_uuid:
        params["clientUserMessageId"] = input_uuid
    return {"jsonrpc": "2.0", "id": APP_TURN_ID, "method": "turn/start", "params": params}


def build_codex_app_server_steer(chat_id: str, thread_id: str, turn_id: str, msg_id: str,
                                 text: str, images: Optional[List[str]] = None) -> Dict:
    """One mid-turn `turn/steer` request for the message.

    `expectedTurnId` is the precondition app-server enforces, and the request id
    is the input's native uuid, so the response correlates with the ledger.
    """
    native = native_input_uuid(chat_id, msg_id)
    inputs: List[Dict] = [{"type": "text", "text": text}]
    for path in images or []:
        inputs.append({"type": "localImage", "path": path})
    return {
        "jsonrpc": "2.0", "id": native, "method": "turn/steer",
        "params": {
            "threadId": thread_id,
            "expectedTurnId": turn_id,
            "input": inputs,
            "clientUserMessageId": native,
        },
    }


def _app_server_append_stdin(client, chat_id: str, payload: str) -> None:
    _ssh_exec(
        client,
        f"printf '%s\\n' {_shell_quote(payload)} >> {_shell_quote(f'/tmp/cc-{chat_id}.stdin')}",
    )


def _app_server_write_stdin(client, chat_id: str, commands: List[Dict]) -> None:
    payload = "".join(json.dumps(command) + "\n" for command in commands)
    sftp = client.open_sftp()
    try:
        with sftp.open(f"/tmp/cc-{chat_id}.stdin", "w") as handle:
            handle.write(payload)
    finally:
        sftp.close()


def _app_server_parse_initial(obj: Dict) -> Optional[str]:
    thread = None
    if obj.get("id") == APP_THREAD_ID and isinstance(obj.get("result"), dict):
        thread = obj["result"].get("thread")
    elif obj.get("method") == "thread/started":
        params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
        thread = params.get("thread")
    thread_id = thread.get("id") if isinstance(thread, dict) else None
    if isinstance(thread_id, str) and _THREAD_ID_RE.fullmatch(thread_id):
        return thread_id
    return None


def _app_server_build_exec(cmd: List[str], chat_id: str, prompt: str,
                           images: Optional[List[str]] = None) -> str:
    """Build `tail -f <stdin> | codex app-server ...` with tail cleanup.

    The launch commands and steers are appended to the stdin file, so the tail
    is the long-lived input channel. The pipeline is backgrounded so the wrapper
    stops the tail once app-server exits; the wrapper's status is app-server's.
    """
    app_cmd = " ".join(_shell_quote(part) for part in cmd)
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    tail_pattern = _shell_quote(f"^tail -f -n \\+1 /tmp/cc-{chat_id}\\.stdin$")
    return (
        f"( tail -f -n +1 {_shell_quote(stdin_file)} | {app_cmd} & _y_app=$!; "
        "while kill -0 $_y_app 2>/dev/null; do sleep 0.2; done; "
        f"pkill -f {tail_pattern} 2>/dev/null; "
        "wait $_y_app )"
    )


def _app_server_stop_stdin_cmd(chat_id: str) -> str:
    """Stop the stdin producer so app-server sees EOF and exits cleanly.

    Used when the two-phase launch could not observe a thread id: a live but
    turn-less app-server would otherwise wait on the pipe until the hard
    timeout. app-server flushes any pending JSON-RPC error first, so the tail
    still reads a refusal written before EOF.
    """
    tail_pattern = _shell_quote(f"^tail -f -n \\+1 /tmp/cc-{chat_id}\\.stdin$")
    return f"pkill -f {tail_pattern} 2>/dev/null || true"


def _codex_app_server_spec(*, thread_id: Optional[str], cwd: Optional[str],
                           model: Optional[str], input_uuid: Optional[str],
                           stage_home: bool = True,
                           launch_env: Optional[Dict[str, str]] = None,
                           model_catalog: Optional[Tuple[List[str], str]] = None) -> "DetachBackendSpec":
    """Launch hooks for one app-server turn (fresh or resumed)."""
    from agent.detach import DetachBackendSpec

    catalog = model_catalog or (None, None)
    home: Dict[str, str] = {}

    def setup(client, chat_id, prompt, images):
        if catalog[0] is not None:
            _stage_model_catalog(client, catalog[0], chat_id, catalog[1])
        if stage_home:
            home["path"] = _stage_app_server_home(client, chat_id)
        if thread_id:
            # Only this thread's rollout is staged, so app-server never has to
            # backfill the node's whole session history before `initialize`.
            codex_home = home.get("path") or (launch_env or {}).get("CODEX_HOME")
            if codex_home:
                _ssh_exec(client, _stage_resume_rollout_cmd(thread_id, codex_home))
        _app_server_write_stdin(
            client, chat_id,
            build_codex_app_server_launch(thread_id, cwd, model),
        )

    def after_initial(client, chat_id, prompt, images, initial_id):
        if not initial_id:
            logger.warning(
                "codex app-server thread id not observed chat_id={}; stopping stdin", chat_id,
            )
            _ssh_exec(client, _app_server_stop_stdin_cmd(chat_id))
            return
        _app_server_append_stdin(
            client, chat_id,
            json.dumps(build_codex_app_server_turn(initial_id, prompt, images, input_uuid)),
        )

    def cleanup():
        path = home.get("path")
        return f"rm -rf {_shell_quote(path)}" if path else "true"

    from agent.tmp_guard import CODEX_APP_SERVER_DISK_FLOOR_BYTES
    return DetachBackendSpec(
        build_exec=_app_server_build_exec,
        parse_initial=_app_server_parse_initial,
        setup=setup,
        after_initial=after_initial,
        cleanup=cleanup,
        # No EXIT trap: a crashed app-server must not delete its rollout before
        # the tail copies it back. The tail removes the home after syncing, and
        # the next launch recreates it anyway.
        trap_cleanup=lambda: "true",
        initial_stdout_lines=60,
        initial_wait_seconds=10.0,
        # Staging this harness's private CODEX_HOME costs ~96 MB before launch.
        free_space_floor_bytes=CODEX_APP_SERVER_DISK_FLOOR_BYTES,
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
    harness: Optional[str] = None,
    resume_thread_id: Optional[str] = None,
    input_uuid: Optional[str] = None,
    exam_isolation: bool = False,
) -> Optional[str]:
    """Start one detached Codex turn in a tmux session on the chat's node.

    `codex exec` (the default) takes the prompt as a positional argument and
    does not read stdin; a steer ends the turn. `harness="app-server"` runs
    `codex app-server --listen stdio://` behind a stdin pipe; the launch
    commands open the thread and `after_initial` appends `turn/start` once the
    thread id is known. stdout / stderr / exit files use `/tmp/cc-<chat_id>.*`.
    When the model has a known context window, the node's bundled catalog is
    cloned into a per-launch catalog so Codex reports and uses that window.

    Returns the thread id from the initial events, else None.
    """
    from agent.detach import _start_detached_tmux, _with_ssh_client

    app_server = (harness or "").strip().lower() == CODEX_APP_SERVER_HARNESS
    build_catalog = bool(model) and bool(context_window)
    if app_server and not exam_isolation:
        # app-server has no --ignore-user-config: the staged home *is* the
        # isolation, so it must reach the process through the launch env.
        env = dict(env or {})
        env["CODEX_HOME"] = codex_app_server_home(chat_id)

    def spec_for(catalog=None):
        if app_server:
            return _codex_app_server_spec(
                thread_id=resume_thread_id, cwd=cwd, model=model,
                input_uuid=input_uuid, stage_home=not exam_isolation,
                launch_env=env, model_catalog=catalog,
            )
        return _codex_spec(catalog)

    spec = spec_for()
    if build_catalog:
        with _with_ssh_client(node, ssh_client) as client:
            catalog = _catalog_from_node(client, cmd, node, model, context_window)
            if catalog is not None:
                spec = spec_for((cmd, json.dumps(catalog)))
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


def app_server_usage(total) -> Optional[Dict]:
    """Exec-shaped counters from a v2 `TokenUsageBreakdown` (a thread total)."""
    if not isinstance(total, dict):
        return None
    usage = {
        "input_tokens": total.get("inputTokens"),
        "cached_input_tokens": total.get("cachedInputTokens"),
        "output_tokens": total.get("outputTokens"),
        "cache_write_input_tokens": total.get("cacheWriteInputTokens"),
    }
    if not any(value is not None for value in usage.values()):
        return None
    return usage


def app_server_item_event(method: str, item: Dict) -> Optional[Dict]:
    """Fold one v2 `ThreadItem` into the exec item event shape the converter maps.

    Only the item kinds the exec converter renders are produced: assistant text,
    command executions and file changes. Reasoning, plans, MCP calls and other
    item kinds stay out of the transcript, exactly as on the exec harness.
    """
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    item_id = item.get("id") or generate_message_id()

    if item_type == "agentMessage":
        if method != "item/completed":
            return None
        text = item.get("text")
        if not isinstance(text, str) or not text:
            return None
        return {
            "type": "item.completed",
            "item": {"id": item_id, "type": "agent_message", "text": text},
        }

    if item_type == "commandExecution":
        payload = {
            "id": item_id,
            "type": "command_execution",
            "command": item.get("command") or "",
        }
        if method == "item/started":
            payload["status"] = "in_progress"
            return {"type": "item.started", "item": payload}
        if method != "item/completed":
            return None
        payload["aggregated_output"] = item.get("aggregatedOutput")
        payload["exit_code"] = item.get("exitCode")
        payload["status"] = item.get("status")
        return {"type": "item.completed", "item": payload}

    if item_type == "fileChange":
        changes = _app_server_file_changes(item)
        payload: Dict = {"id": item_id, "type": "file_change", "changes": changes}
        if method == "item/started":
            payload["status"] = "in_progress"
            return {"type": "item.started", "item": payload}
        if method != "item/completed":
            return None
        payload["status"] = item.get("status")
        diffs = [
            change.get("diff") for change in changes
            if isinstance(change.get("diff"), str) and change.get("diff")
        ]
        if diffs:
            payload["diff"] = "\n".join(diffs)
        return {"type": "item.completed", "item": payload}

    return None


def _app_server_file_changes(item: Dict) -> List[Dict]:
    """Normalize v2 `FileUpdateChange` entries into the exec-shaped changes list.

    v2 `PatchChangeKind` is a tagged object (`{"type": "update", ...}`), while
    the exec item carries the kind as a string. The tagged payload is replaced
    by its type so the converter's summary renders `update <path>`, not the
    raw dict.
    """
    raw = item.get("changes")
    changes = raw if isinstance(raw, list) else []
    normalized = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        entry = dict(change)
        kind = entry.get("kind")
        if isinstance(kind, dict):
            entry["kind"] = kind.get("type") or "change"
        elif not isinstance(kind, str):
            entry["kind"] = entry.get("type") if isinstance(entry.get("type"), str) else "change"
        normalized.append(entry)
    return normalized


def app_server_turn_event(turn: Dict, usage: Optional[Dict]) -> Optional[Dict]:
    """The exec terminal event for a finished v2 turn, or None while running."""
    if not isinstance(turn, dict):
        return None
    status = turn.get("status")
    if status == "completed":
        event: Dict = {"type": "turn.completed"}
        if usage:
            event["usage"] = usage
        return event
    if status == "failed":
        error = turn.get("error") if isinstance(turn.get("error"), dict) else {}
        message = error.get("message") or "Turn failed"
        return {"type": "turn.failed", "error": {"message": message}}
    return None


def app_server_missing_rollout(error, attempted_id: Optional[str]) -> bool:
    """True only for the native missing-rollout refusal of the attempted id."""
    if not isinstance(error, dict) or not isinstance(attempted_id, str) or not attempted_id:
        return False
    if error.get("code") != -32600:
        return False
    message = error.get("message")
    if not isinstance(message, str):
        return False
    match = _MISSING_ROLLOUT_MESSAGE_RE.search(message)
    return bool(match and match.group(1) == attempted_id)


def _missing_rollout_stderr_line(thread_id: str) -> str:
    """The existing stderr diagnostic shape for the shared recovery decision."""
    return (
        "Error: thread/resume: thread/resume failed: no rollout found for thread id "
        f"{thread_id} (code -32600)"
    )


def _app_server_request_id(value) -> bool:
    """JSON-RPC `RequestId` is a string or an int64; bool is never an id."""
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _app_server_pending(state: Dict, terminal_status: Optional[str] = None,
                        result_data=None, extra_view: Optional[Dict] = None) -> dict:
    """Handoff state: ids, thread total and any terminal turn already observed.

    A cancellation can land after the reader handled `turn/completed` (or a
    fatal request error) but before teardown. Carrying the terminal status and
    its result lets the next invocation tear the long-lived app-server down
    instead of tailing past the terminal line into the hard timeout.
    """
    return {
        "type": APP_SERVER_PENDING_TYPE,
        "thread_id": state.get("thread_id"),
        "turn_id": state.get("turn_id"),
        "usage": state.get("usage"),
        "thread_observed": bool(state.get("thread_observed")),
        "terminal_status": terminal_status,
        "result_data": result_data,
        "extra_view": dict(extra_view or {}),
    }


async def tail_codex_app_server_output(
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
    session_id: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Tail a detached `codex app-server` turn; steer through its stdin pipe.

    `check_steer_fn` supplies messages accepted mid-run. A steer appends one
    `turn/steer` request carrying `expectedTurnId` and the input's native uuid;
    it never ends the turn. The response's `{turnId}` acknowledges it, a
    `-32600` (no active turn / wrong id) drops it for the closeout continuation,
    and the `userMessage` item with that `clientId` completes it. A steer still
    open at `turn/completed` stays open.

    `turn/completed` (completed / failed / interrupted) ends the turn: the
    reader stops and the long-lived app-server is torn down, with no self-kill
    sentinel because the terminal event is the evidence. A resumed refusal
    (`-32600 no rollout found`) feeds the same recovery inputs as the exec
    path's stderr refusal. A Lambda handoff carries thread id, turn id and the
    thread usage total; a re-attached tail without a turn id asks
    `thread/turns/list` for the in-progress turn.
    """
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    client = ssh_client
    stdin_file = f"/tmp/cc-{chat_id}.stdin"
    stdout_file = f"/tmp/cc-{chat_id}.stdout"
    exit_file = f"/tmp/cc-{chat_id}.exit"

    converter = CodexStreamConverter(last_message_id=last_message_id, model=model)
    ledger = input_ledger if input_ledger is not None else InputLedger(chat_id)
    state: Dict = {"thread_id": None, "turn_id": None, "usage": None,
                   "thread_observed": False}
    if isinstance(session_id, str) and session_id:
        state["thread_id"] = session_id
    carried = pending_result if isinstance(pending_result, dict) else None
    terminal_status: Optional[str] = None
    extra_view: Dict = {}
    restored_result = None
    if carried and carried.get("type") == APP_SERVER_PENDING_TYPE:
        for key in ("thread_id", "turn_id", "usage"):
            value = carried.get(key)
            if value is not None:
                state[key] = value
        if "thread_observed" in carried:
            state["thread_observed"] = bool(carried.get("thread_observed"))
        else:
            # Old record: a carried thread id proves the response arrived.
            state["thread_observed"] = bool(state["thread_id"])
        restored_terminal = carried.get("terminal_status")
        if isinstance(restored_terminal, str) and restored_terminal:
            terminal_status = restored_terminal
            restored_result = carried.get("result_data")
            carried_view = carried.get("extra_view")
            if isinstance(carried_view, dict):
                extra_view.update(carried_view)
        carried = None
    if state["thread_id"]:
        converter.thread_id = state["thread_id"]

    result_data = restored_result if terminal_status is not None else carried
    current_offset = offset
    stream_error = None
    poll = None
    stdout_ch = None
    # Guards the steer write and the terminal teardown: a steer must never be
    # appended after the session was torn down.
    steer_lock = threading.RLock()
    torn_down = False
    home_disposed = False
    reader_stop = threading.Event()

    def _view(is_done: bool, status: str, data=None) -> dict:
        view = {
            "offset": current_offset,
            "last_message_id": converter.last_message_id,
            "thread_id": state["thread_id"],
            "session_id": state["thread_id"],
            "is_done": is_done,
            "result_data": data,
            "usage": converter.usage,
            "status": status,
            "delivery_states": ledger.states,
            "input_groups": ledger.groups,
            "lifecycle_observed": ledger.lifecycle_observed,
            "has_usable_output": converter.has_usable_output,
            "pending_result": (None if is_done else _app_server_pending(
                state, terminal_status=terminal_status, result_data=data,
                extra_view=extra_view,
            )),
        }
        view.update(extra_view)
        return view

    def _emit(event: Dict) -> None:
        for msg in converter.process_event(event):
            if message_callback:
                message_callback(msg)

    def _handle_turns_list(result) -> None:
        if state["turn_id"] or not isinstance(result, dict):
            return
        turns = result.get("data")
        for turn in turns if isinstance(turns, list) else []:
            if isinstance(turn, dict) and turn.get("status") == "inProgress":
                turn_id = turn.get("id")
                if isinstance(turn_id, str) and turn_id:
                    state["turn_id"] = turn_id
                return

    def _end_error(message: Optional[str]) -> str:
        nonlocal result_data, terminal_status
        text = message if isinstance(message, str) and message else "app-server request failed"
        logger.error("codex app-server error: chat_id={} message={}", chat_id, text)
        result_data = {"is_error": True, "result": format_codex_turn_failure(text)}
        terminal_status = "failed"
        return "done"

    def _end_thread_error(error) -> str:
        nonlocal result_data, terminal_status
        error = error if isinstance(error, dict) else {}
        message = error.get("message") if isinstance(error.get("message"), str) else None
        if app_server_missing_rollout(error, resume_thread_id):
            # Same recovery inputs the exec path derives from its stderr line.
            extra_view["exit_code"] = 1
            extra_view["attempt_stderr"] = _missing_rollout_stderr_line(resume_thread_id)
            extra_view["startup_diagnostic"] = message
            extra_view["resume_refused"] = True
            extra_view["refused_thread_id"] = resume_thread_id
        return _end_error(message)

    def _complete_steer_item(method: str, item: Dict) -> None:
        if item.get("type") != "userMessage":
            return
        client_id = item.get("clientId")
        if not isinstance(client_id, str):
            return
        # The lock is the ordering point: `_on_steer` marks the write submitted
        # while holding it, so a fast response/item cannot miss the group.
        with steer_lock:
            if client_id not in ledger.groups:
                return
            if client_id == launch_input_uuid:
                # The folded launch prompt retires on turn/completed.
                return
            ledger.observe_lifecycle({"state": "completed", "command_uuid": client_id})

    def _handle_response(request_id: str, result, error) -> Optional[str]:
        if request_id == APP_INIT_ID:
            if error is not None:
                return _end_error((error or {}).get("message") if isinstance(error, dict) else None)
            return None
        if request_id == APP_THREAD_ID:
            # Any response to the thread request (success or refusal) means
            # app-server answered; a silent exit afterwards is not a startup.
            state["thread_observed"] = True
            if error is not None:
                return _end_thread_error(error)
            thread = result.get("thread") if isinstance(result, dict) else None
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if isinstance(thread_id, str) and thread_id:
                state["thread_id"] = thread_id
                converter.thread_id = thread_id
            return None
        if request_id == APP_TURN_ID:
            if error is not None:
                return _end_error((error or {}).get("message") if isinstance(error, dict) else None)
            turn = result.get("turn") if isinstance(result, dict) else None
            turn_id = turn.get("id") if isinstance(turn, dict) else None
            if isinstance(turn_id, str) and turn_id and not state["turn_id"]:
                state["turn_id"] = turn_id
            return None
        if request_id == APP_TURNS_LIST_ID:
            _handle_turns_list(result)
            return None
        with steer_lock:
            # Same ordering rule as the item completion: the response may be
            # read before the steer write's SSH exit status returns.
            if request_id not in ledger.groups:
                return None
            state_name = "queued" if error is None else "refused"
            ledger.observe_lifecycle({"state": state_name, "command_uuid": request_id})
        return None

    def _handle_notification(method: str, params: Dict) -> Optional[str]:
        nonlocal result_data, terminal_status
        if method == "thread/started":
            state["thread_observed"] = True
            thread = params.get("thread") if isinstance(params.get("thread"), dict) else {}
            thread_id = thread.get("id")
            if isinstance(thread_id, str) and thread_id:
                state["thread_id"] = thread_id
                converter.thread_id = thread_id
            return None
        if method == "turn/started":
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id and not state["turn_id"]:
                state["turn_id"] = turn_id
            return None
        if method == "thread/tokenUsage/updated":
            # A resume replays the previous turn's notification before
            # `turn/started`, so a missing turn id must not consume it: only
            # the current turn's total may feed this turn's usage.
            if not state["turn_id"] or params.get("turnId") != state["turn_id"]:
                return None
            token_usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
            usage = app_server_usage(token_usage.get("total"))
            if usage is not None:
                state["usage"] = usage
            return None
        if method in ("item/started", "item/completed"):
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            _complete_steer_item(method, item)
            event = app_server_item_event(method, item)
            if event is not None:
                _emit(event)
            return None
        if method == "error":
            error = params.get("error") if isinstance(params.get("error"), dict) else {}
            message = error.get("message") if isinstance(error.get("message"), str) else "Unknown error"
            _emit({"type": "error", "message": message})
            return None
        if method == "turn/completed":
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id and not state["turn_id"]:
                state["turn_id"] = turn_id
            status = turn.get("status")
            if status == "completed":
                event = app_server_turn_event(turn, state["usage"]) or {"type": "turn.completed"}
                if event.get("usage"):
                    converter.usage = normalize_usage(event["usage"])
                with steer_lock:
                    _complete_launch_group(ledger, launch_input_uuid)
                result_data = event
                terminal_status = "completed"
                return "done"
            if status == "failed":
                event = app_server_turn_event(turn, None) or {
                    "type": "turn.failed", "error": {"message": "Turn failed"},
                }
                _emit(event)
                # The exec path reports the same bounded diagnostic shape so
                # closeout stores the real failure text, not a generic one.
                result_data = _codex_failure_data(event["error"].get("message"))
                terminal_status = "failed"
                return "done"
            if status == "interrupted":
                result_data = None
                terminal_status = "interrupted"
                return "done"
            return None
        return None

    def _handle_message(obj: Dict) -> Optional[str]:
        request_id = obj.get("id")
        if _app_server_request_id(request_id) and isinstance(obj.get("method"), str):
            # A server-to-client request (approval / elicitation / auth). None
            # are expected under the staged policy; refuse rather than stall.
            logger.warning(
                "codex app-server client request refused chat_id={} method={}",
                chat_id, obj.get("method"),
            )
            try:
                _app_server_append_stdin(client, chat_id, json.dumps({
                    "jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32601, "message": "y-agent does not support client requests"},
                }))
            except Exception as exc:
                logger.warning("codex app-server client-request refusal failed: {}", exc)
            return None
        if isinstance(request_id, str) and ("result" in obj or obj.get("error") is not None):
            return _handle_response(request_id, obj.get("result"), obj.get("error"))
        if not isinstance(obj.get("method"), str):
            # The shared launcher writes its own error lines into the same
            # stdout file (e.g. the missing-work-dir result). Surface them
            # instead of letting the process death hide the cause.
            if obj.get("type") == "result" and obj.get("is_error"):
                return _end_error(obj.get("result"))
            if obj.get("type") == "error" and isinstance(obj.get("message"), str):
                return _end_error(obj.get("message"))
        method = obj.get("method")
        if isinstance(method, str):
            params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
            return _handle_notification(method, params)
        return None

    def _teardown_session(*, kill: bool, self_killed: bool = False) -> None:
        """One staged-home lifecycle for every session-ending exit.

        Handoff exits never call this: a deadline, a cancellation or a set
        `reader_stop` keeps the staged home (and its rollout) alive for the
        re-attach. Every other exit does, and a watchdog/reader race runs
        the remote work exactly once: under `steer_lock` it marks the
        session torn down, copies the staged rollouts back, optionally
        kills the process group (with the self-kill sentinel only for our
        own interrupt), copies again, removes the staged home, and closes
        the stdout channel.
        """
        nonlocal torn_down, home_disposed
        with steer_lock:
            torn_down = True
            if home_disposed:
                return
            home_disposed = True
            _sync_app_server_rollouts(client, chat_id)
            if kill:
                try:
                    if self_killed:
                        _kill_session_marking_self_killed(client, chat_id, node=node)
                    else:
                        from agent.detach import _tmux_kill_cmd

                        _ssh_exec(client, _tmux_kill_cmd(chat_id, node=node))
                except Exception as exc:
                    logger.warning(
                        "codex app-server teardown failed chat_id={}: {}", chat_id, exc,
                    )
            _sync_app_server_rollouts(client, chat_id)
            _remove_app_server_home(client, chat_id)
        channel = stdout_ch
        if channel is not None:
            try:
                channel.channel.close()
            except Exception:
                pass

    def _on_interrupt():
        logger.info("interrupt watchdog (codex app-server): killing tmux session cc-{}", chat_id)
        _teardown_session(kill=True, self_killed=True)

    try:
        tail_cmd = _build_tail_cmd(stdout_file, exit_file, offset, node=node)
        stdin_ch, stdout_ch, stderr_ch = client.exec_command(tail_cmd)

        if not state["turn_id"] and state["thread_id"] and offset > 0:
            # Re-attached tail: recover the live turn id from the server.
            try:
                _app_server_append_stdin(client, chat_id, json.dumps({
                    "jsonrpc": "2.0", "id": APP_TURNS_LIST_ID, "method": "thread/turns/list",
                    "params": {"threadId": state["thread_id"], "limit": 5},
                }))
            except Exception as exc:
                logger.warning(
                    "codex app-server turns/list recovery failed chat_id={}: {}", chat_id, exc,
                )

        def _on_steer(text, msg_id, images=None) -> bool:
            """Append a `turn/steer` request to the live stdin pipe.

            The turn is not ended: app-server admits the message into the
            current turn. A zero write status only proves the bytes reached the
            file; the request's response acknowledges or drops it, and the
            `userMessage` item with its clientId completes it. A False return
            releases the poll checker's claim so closeout re-delivers it.
            """
            with steer_lock:
                if torn_down or reader_stop.is_set() or terminal_status:
                    return False
                thread_id = state["thread_id"]
                turn_id = state["turn_id"]
                if not thread_id or not turn_id:
                    return False
                try:
                    from agent.detach import upload_steer_images

                    remote_images = upload_steer_images(client, chat_id, msg_id, images)
                except Exception as exc:
                    logger.warning(
                        "codex app-server steer image staging failed chat_id={} message={}: {}",
                        chat_id, msg_id, exc,
                    )
                    return False
                payload = json.dumps(build_codex_app_server_steer(
                    chat_id, thread_id, turn_id, msg_id, text, remote_images,
                ))
                _, write_stdout, _ = client.exec_command(
                    f"printf '%s\\n' {_shell_quote(payload)} >> {_shell_quote(stdin_file)}"
                )
                if write_stdout.channel.recv_exit_status() != 0:
                    return False
                converter.last_message_id = msg_id
                ledger.mark_submitted(native_input_uuid(chat_id, msg_id), [msg_id])
            logger.info("codex app-server steer: queued chat_id={} for message={}", chat_id, msg_id)
            return True

        poll = PollLoop(
            check_interrupted_fn=check_interrupted_fn,
            on_interrupt=_on_interrupt,
            check_steer_fn=check_steer_fn,
            on_steer=_on_steer,
        )
        poll.start()

        def _read_lines():
            nonlocal current_offset, stream_error, torn_down
            if terminal_status is not None:
                # A handoff carried a terminal turn (the cancellation landed
                # after `turn/completed` was handled but before teardown was
                # safe): tear the long-lived app-server down before tailing,
                # instead of following stdout past the terminal line.
                if reader_stop.is_set():
                    return "deadline"
                _teardown_session(kill=True)
                return None
            try:
                for raw_line in stdout_ch:
                    if reader_stop.is_set():
                        return "deadline"
                    line = (raw_line.strip() if isinstance(raw_line, str)
                            else raw_line.decode("utf-8", errors="replace").strip())
                    if not line:
                        continue

                    if check_interrupted_fn and check_interrupted_fn():
                        _teardown_session(kill=True, self_killed=True)
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

                    outcome = _handle_message(obj)
                    if outcome == "done":
                        if reader_stop.is_set():
                            return "deadline"
                        _teardown_session(kill=True)
                        return None
            except (OSError, EOFError, Exception) as exc:
                if check_interrupted_fn and check_interrupted_fn():
                    _teardown_session(kill=True, self_killed=True)
                    return "interrupted"
                if not isinstance(exc, (OSError, EOFError)):
                    raise
                stream_error = exc

            if check_interrupted_fn and check_interrupted_fn():
                _teardown_session(kill=True, self_killed=True)
                return "interrupted"
            return None

        loop = asyncio.get_event_loop()
        reader = loop.run_in_executor(None, _read_lines)
        cancelled = False
        try:
            exit_reason = await asyncio.shield(reader)
        except asyncio.CancelledError:
            logger.info(
                "tail_codex_app_server_output cancelled: chat_id={} offset={}", chat_id, current_offset,
            )
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

        if exit_reason == "interrupted":
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            return _view(True, "interrupted", None)

        if exit_reason == "deadline":
            if owns_client:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            return _view(False, "monitoring", result_data)

        status = None
        data = result_data
        if terminal_status == "completed":
            status = "completed"
        elif terminal_status == "failed":
            status = "error"
        elif terminal_status == "interrupted":
            status, data = "interrupted", None

        if status is None:
            status = "monitoring"
            if _consume_self_kill_sentinel(client, chat_id):
                status, data = "interrupted", None
            elif _tmux_session_alive(client, chat_id, node=node):
                pass
            else:
                # The process is gone: publish whatever rollout it wrote and
                # remove the staged home before reporting the failure.
                _teardown_session(kill=False)
                attempt = read_codex_attempt_diagnostic(client, chat_id, stream_error)
                text = attempt["text"]
                if (not state["thread_observed"] and not converter.has_usable_output
                        and attempt.get("exit_code") == 0):
                    # A silent exit 0 is a startup failure, not a finished
                    # turn: name it instead of "process exited with code 0".
                    text = APP_SERVER_NO_THREAD_ERROR
                extra_view.update(
                    startup_diagnostic=text,
                    exit_code=attempt["exit_code"],
                    attempt_stderr=attempt["stderr"],
                )
                status = "error"
                data = {"is_error": True, "result": text}

        if owns_client:
            from agent.chat_target import close_owned_client
            close_owned_client(client)

        if status == "monitoring":
            logger.warning(
                "tail_codex_app_server_output: chat_id={} no terminal turn event but session still in play (offset={}); resuming monitoring",
                chat_id, current_offset,
            )
            return _view(False, "monitoring", None)
        return _view(True, status, data)

    except Exception as exc:
        logger.error("tail_codex_app_server_output error: {} {}", type(exc).__name__, exc)
        if poll is not None:
            poll.stop()
        # Re-attachable tail failure: dispose the staged home only when the
        # session is provably gone. A live app-server keeps its home for the
        # next attempt, because removing it would truncate the rollout.
        try:
            if not _tmux_session_alive(client, chat_id, node=node):
                _teardown_session(kill=False)
        except Exception:
            pass
        if owns_client:
            try:
                from agent.chat_target import close_owned_client
                close_owned_client(client)
            except Exception:
                pass
        return _view(False, "error", None)
