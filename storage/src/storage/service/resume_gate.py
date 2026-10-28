"""Deterministic admission guard for expensive long-context resumes."""

import os
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone

from storage.dto.chat import Chat


class ChatReadOnly(Exception):
    reason = "opus_context_limit"

    def __init__(self, measured_tokens: int, limit_tokens: int, handoff=None):
        self.measured_tokens = measured_tokens
        self.limit_tokens = limit_tokens
        self.handoff = handoff or {}
        super().__init__(
            f"Chat is read-only: its latest prompt ({measured_tokens:,} tokens) "
            f"reached the resume limit ({limit_tokens:,} tokens). Continue in a new chat from durable state."
        )

    def detail(self) -> dict:
        return {
            "code": "chat_read_only", "reason": self.reason, "message": str(self),
            "measured_tokens": self.measured_tokens, "limit_tokens": self.limit_tokens,
            "handoff": self.handoff,
        }


def measure(chat: Chat):
    return chat.prompt_tokens()


@dataclass(frozen=True)
class Measurement:
    """One decision's trusted prompt size. `tokens` is None when it is unknown."""

    tokens: int | None
    source: str
    request_id: str | None = None
    session_id: str | None = None
    requested_at: str | None = None


UNKNOWN = Measurement(None, "unknown")
_BOUNDARY_UNKNOWN = object()
_PROMPT_COUNTERS = ("input_tokens", "cache_read_tokens", "cache_creation_tokens")


def effective_limit(bot_config):
    if bot_config is None:
        return None
    limit = bot_config.resume_context_limit
    if limit is None:
        if "opus" not in (bot_config.model or "").lower():
            return None
        limit = int(os.getenv("Y_AGENT_OPUS_RESUME_CONTEXT_LIMIT", "100000"))
    return limit if limit > 0 else None


def pick_limit(current_limit, pending_limit, measured):
    """Current bot wins when it is already over its limit; otherwise the tighter one."""
    if current_limit is not None and measured is not None and measured >= current_limit:
        return current_limit
    limits = [value for value in (current_limit, pending_limit) if value is not None]
    return min(limits) if limits else None


def limit_bounds(user_id: int, chat: Chat, bot_name=None, bot_tier=None):
    """Current and pending limits. No usage read, so admission can do this before the lock."""
    from agent.config import _resolve_named, resolve_pinned_bot_config

    if chat.backend != "claude_code" or not chat.external_id:
        return None, None
    current = _resolve_named(user_id, chat.bot_name, backend=chat.backend)
    current_limit = effective_limit(current)
    pending_limit = None
    if bot_name and bot_name != chat.bot_name:
        config = resolve_pinned_bot_config(user_id, bot_name, bot_tier)
        if config and (config.backend or config.api_type) != chat.backend:
            config = None
        if config is None:
            config = current
        pending_limit = effective_limit(config)
    return current_limit, pending_limit


def resolve_limit(user_id: int, chat: Chat, bot_name=None, bot_tier=None, *, measured=None):
    current_limit, pending_limit = limit_bounds(user_id, chat, bot_name, bot_tier)
    if measured is None:
        measured = measure(chat)
    return pick_limit(current_limit, pending_limit, measured)


def _parse_requested_at(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _message_floor(chat: Chat, pending_input_ids, boundary_reliable: bool):
    """Latest persisted user-message time, excluding this launch's pending inputs.

    Millisecond `unix_timestamp` values match the chat DTO. A missing or
    non-integer stamp makes the boundary unreliable. Refusal notices are
    assistant messages and do not count.
    """
    if not boundary_reliable:
        return _BOUNDARY_UNKNOWN
    pending = {item for item in (pending_input_ids or ()) if item}
    latest = None
    for msg in chat.messages or []:
        if getattr(msg, "role", None) != "user":
            continue
        if getattr(msg, "id", None) in pending:
            continue
        stamp = getattr(msg, "unix_timestamp", None)
        if isinstance(stamp, bool) or not isinstance(stamp, int):
            return _BOUNDARY_UNKNOWN
        if latest is None or stamp > latest:
            latest = stamp
    if latest is None:
        return None
    try:
        return datetime.fromtimestamp(latest / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _BOUNDARY_UNKNOWN


def _row_measurement(rows, floor, now, session_id: str, chat_id: str):
    """Validate the newest row only. The second row exists to detect a tie."""
    from storage.service.chat_request_usage import REQUESTED_AT_FUTURE, _counter

    if not rows:
        return UNKNOWN
    parsed = [_parse_requested_at(getattr(row, "requested_at", None)) for row in rows]
    if any(item is None for item in parsed) or (len(parsed) > 1 and parsed[0] == parsed[1]):
        return UNKNOWN
    newest = rows[0]
    if getattr(newest, "session_id", None) != session_id or getattr(newest, "chat_id", None) != chat_id:
        return UNKNOWN
    when = parsed[0]
    if when > now + REQUESTED_AT_FUTURE or floor is _BOUNDARY_UNKNOWN or (floor is not None and when < floor):
        return UNKNOWN
    if getattr(newest, "usage_state", None) != "observed":
        return UNKNOWN
    counters = []
    for name in _PROMPT_COUNTERS:
        value = _counter(getattr(newest, name, None))
        if value is None:
            return UNKNOWN
        counters.append(value)
    request_id = getattr(newest, "request_id", None)
    if not isinstance(request_id, str) or not request_id:
        return UNKNOWN
    if floor is not None and when == floor:
        from loguru import logger

        logger.info("resume_gate freshness boundary equal at stored timestamp precision")
    return Measurement(sum(counters), "request_usage", request_id, session_id, when.isoformat())


def resolve_measurement(user_id: int, chat: Chat, *, session=None, pending_input_ids=None,
                        live_steer: bool = False, limit_applicable: bool = True,
                        boundary_reliable: bool = True, now=None):
    """Trusted prompt evidence for one decision, or unknown. At most one usage read."""
    if live_steer or not limit_applicable or chat.backend != "claude_code" or not chat.external_id:
        return UNKNOWN
    source = chat.context_usage_source
    if source == "main_request":
        tokens = chat.prompt_tokens()
        return Measurement(tokens, "main_request") if tokens is not None else UNKNOWN
    if source is not None:
        return UNKNOWN
    floor = _message_floor(chat, pending_input_ids, boundary_reliable)
    if floor is _BOUNDARY_UNKNOWN:
        return UNKNOWN
    from storage.repository import chat_request_usage as usage_repo

    rows = usage_repo.latest_session_rows(user_id, chat.id, chat.external_id, session=session)
    if rows is None:
        return UNKNOWN
    return _row_measurement(rows, floor, now or datetime.now(timezone.utc), chat.external_id, chat.id)


def evaluate(user_id: int, chat: Chat, bot_name=None, bot_tier=None, *, bot_config=None,
             measurement=None, pending_input_ids=None, session=None, boundary_reliable: bool = True):
    """Evaluate a resume, including worker launches whose reservation is running."""
    if chat.backend != "claude_code" or not chat.external_id:
        return None
    if measurement is None:
        if bot_config is not None:
            applicable = effective_limit(bot_config) is not None
        else:
            current_limit, pending_limit = limit_bounds(user_id, chat, bot_name, bot_tier)
            applicable = current_limit is not None or pending_limit is not None
        measurement = resolve_measurement(
            user_id, chat, session=session, pending_input_ids=pending_input_ids,
            limit_applicable=applicable, boundary_reliable=boundary_reliable,
        )
    limit = (effective_limit(bot_config) if bot_config is not None
             else resolve_limit(user_id, chat, bot_name, bot_tier, measured=measurement.tokens))
    if limit is None or measurement.tokens is None or measurement.tokens < limit:
        return None
    return ChatReadOnly(measurement.tokens, limit, build_handoff(user_id, chat))


def append_refusal_notice(user_id: int, chat_id: str, event_id: str, refusal: ChatReadOnly):
    from storage.entity.dto import Message
    from storage.service.chat import append_message_sync
    from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp

    from loguru import logger

    try:
        append_message_sync(chat_id, Message(
            id=f"msg_resume_gate_{event_id}", role="assistant",
            content=f"Scheduled delivery refused (chat_read_only:{refusal.reason}). {refusal}",
            timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
        ), user_id=user_id)
    except Exception:
        logger.exception("Unable to append resume-gate notice for chat {}", chat_id)


def build_handoff(user_id: int, chat: Chat) -> dict:
    from storage.service import note, note_todo_relation, todo

    progress = ""
    paths = []
    if chat.trace_id:
        task = todo.get_todo(user_id, chat.trace_id)
        if task:
            progress = (task.progress or "")[:600]
            ids = note_todo_relation.list_by_todo(user_id, chat.trace_id)[:10]
            paths = [n.content_key for n in note.get_notes_by_ids(user_id, ids) if n.content_key][:10]
    prompt = (
        f"Continue trace {chat.trace_id or '(untraced)'} from read-only chat {chat.id}; "
        "read the todo progress and associated notes; do not replay the old transcript."
    )
    if progress:
        prompt += f"\nProgress: {progress}"
    if paths:
        prompt += "\nNotes: " + ", ".join(paths)
    args = ["y", "chat", "--new"]
    for flag, value in (("--trace-id", chat.trace_id), ("--role", chat.role),
                        ("--skill", chat.skill), ("--work-dir", chat.work_dir),
                        ("--bot", chat.bot_name)):
        if value:
            args.extend((flag, value))
    args.extend(("-m", prompt))
    return {
        "source_chat_id": chat.id, "trace_id": chat.trace_id, "topic": chat.topic, "role": chat.role,
        "skill": chat.skill, "work_dir": chat.work_dir, "bot_name": chat.bot_name,
        "todo_id": chat.trace_id, "progress": progress, "note_paths": paths,
        "prompt": prompt, "command": shlex.join(args),
    }
