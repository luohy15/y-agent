"""Deterministic admission guard for expensive long-context resumes."""

import os
import shlex

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


def effective_limit(bot_config):
    if bot_config is None:
        return None
    limit = bot_config.resume_context_limit
    if limit is None:
        if "opus" not in (bot_config.model or "").lower():
            return None
        limit = int(os.getenv("Y_AGENT_OPUS_RESUME_CONTEXT_LIMIT", "100000"))
    return limit if limit > 0 else None


def resolve_limit(user_id: int, chat: Chat, bot_name=None, bot_tier=None):
    from agent.config import _resolve_named, resolve_pinned_bot_config

    if chat.backend != "claude_code" or not chat.external_id:
        return None
    current = _resolve_named(user_id, chat.bot_name, backend=chat.backend)
    current_limit = effective_limit(current)
    measured = measure(chat)
    if current_limit is not None and measured is not None and measured >= current_limit:
        return current_limit
    config = None
    if bot_name and bot_name != chat.bot_name:
        config = resolve_pinned_bot_config(user_id, bot_name, bot_tier)
        if config and (config.backend or config.api_type) != chat.backend:
            config = None
    if config is None:
        config = current
    pending_limit = effective_limit(config)
    limits = [limit for limit in (current_limit, pending_limit) if limit is not None]
    return min(limits) if limits else None


def evaluate(user_id: int, chat: Chat, bot_name=None, bot_tier=None, *, bot_config=None):
    """Evaluate a resume, including worker launches whose reservation is running."""
    if chat.backend != "claude_code" or not chat.external_id:
        return None
    limit = (effective_limit(bot_config) if bot_config is not None
             else resolve_limit(user_id, chat, bot_name, bot_tier))
    measured = measure(chat)
    if limit is None or measured is None or measured < limit:
        return None
    return ChatReadOnly(measured, limit, build_handoff(user_id, chat))


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
