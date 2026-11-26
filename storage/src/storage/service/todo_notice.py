"""Localized awaiting-notice text and writer-supplied notice validation.

Todo 4492 moved the notice language off the kernel's hardcoded Chinese default
into the recipient's per-user preference (`user_preference.language`). Headings
and fault sentences sit in closed catalogs so every sentence has a maintained
translation; an unknown language falls back to English. Raw error excerpts and
outcome tokens are evidence and are never translated.
"""

import re
from typing import Optional

from storage.service.user_preference import DEFAULT_LANGUAGE

NOTICE_LIMIT = 200
FAULT_TEXT_LIMIT = 1000

_HEADINGS = {
    "en": "[Progress] {todo_id}",
    "zh": "【进度】{todo_id}",
}

_FAULTS = {
    "en": {
        "idle": "No session is running.",
        "backstop": "Active for more than {hours} hours, but this todo has no session.",
        "session_end": "The session has ended; no other task is running on this todo.",
        "attention": "Session {chat_id} is waiting for your reply.",
        "lapsed_wait": 'The declared machine wait "{on}" lapsed at {until} with no callback.',
        "death": "Todo {todo_id} session {chat_id} ended abnormally ({outcome}).",
        "death_manager": "Todo {todo_id}, chat {chat_id}: observed {outcome}.",
        "chat_suffix": " Recent session {chat_id}: exit status {outcome}.",
    },
    "zh": {
        "idle": "没有正在运行的会话。",
        "backstop": "已活跃超过 {hours} 小时，但该 todo 没有任何会话。",
        "session_end": "会话已结束，该 todo 上没有其他任务在运行。",
        "attention": "会话 {chat_id} 正在等待你的回复。",
        "lapsed_wait": '声明的机器等待 "{on}" 已于 {until} 到期，没有收到回调。',
        "death": "Todo {todo_id} 的会话 {chat_id} 异常结束（{outcome}）。",
        "death_manager": "Todo {todo_id} 的会话 {chat_id} 异常结束（{outcome}）。",
        "chat_suffix": " 最近的会话 {chat_id}：退出状态 {outcome}。",
    },
}

_FAULT_DEFAULTS = {"hours": 24}

_CREDENTIAL_RES = (
    re.compile(r"(?<![A-Za-z0-9])sk-"),
    re.compile(r"(?<![A-Za-z0-9])ghp_"),
    re.compile(r"(?<![A-Za-z0-9])gho_"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_"),
    re.compile(r"(?<![A-Za-z0-9])AKIA"),
    re.compile(r"(?<![A-Za-z0-9])xoxb-"),
    re.compile(r"Bearer "),
    re.compile(r"Authorization:"),
    re.compile(r"://user:pass@"),
)
_MIXED_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/_\-]{40,}(?![A-Za-z0-9])")
_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]+$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"[0-9]")


def notice_heading(todo_id: str, language: str = DEFAULT_LANGUAGE) -> str:
    template = _HEADINGS.get(language) or _HEADINGS[DEFAULT_LANGUAGE]
    return template.format(todo_id=todo_id)


def fault_sentence(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    catalog = _FAULTS.get(language) or _FAULTS[DEFAULT_LANGUAGE]
    template = catalog.get(key) or _FAULTS[DEFAULT_LANGUAGE][key]
    return template.format(**{**_FAULT_DEFAULTS, **values})


def _collapse_notice(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    return collapsed or None


def _matches_credential_shape(text: str) -> bool:
    if any(pattern.search(text) for pattern in _CREDENTIAL_RES):
        return True
    return any(
        not _HEX_TOKEN.fullmatch(token) and _HAS_LETTER.search(token) and _HAS_DIGIT.search(token)
        for token in _MIXED_TOKEN.findall(text)
    )


def validate_notice(text: Optional[str]) -> Optional[str]:
    """Collapse and accept a writer-supplied awaiting summary, or raise.

    Omitted notice stays None. An explicit empty/whitespace summary is
    rejected so the writer cannot think a blank --note was recorded.
    Over-long or credential-shaped text is rejected before any mutation so
    the writer can retry with a shorter, non-secret sentence. Truncating
    or dropping would hide the loss.
    """
    if text is None:
        return None
    collapsed = _collapse_notice(text)
    if collapsed is None:
        raise ValueError("notice must be a non-empty sentence after whitespace collapse")
    if len(collapsed) > NOTICE_LIMIT:
        raise ValueError(
            f"notice must be at most {NOTICE_LIMIT} characters after whitespace collapse; shorten and retry"
        )
    if _matches_credential_shape(collapsed):
        raise ValueError("notice matches a credential shape; omit secrets and retry")
    return collapsed


def notice_excerpt(text: Optional[str]) -> Optional[str]:
    """Bounded machine-fed excerpt, or None when it matches a credential shape.

    Watchdog/death claims cannot retry, so a matching tail is omitted rather
    than rejected. Length is still bounded by FAULT_TEXT_LIMIT.
    """
    collapsed = _collapse_notice(text)
    if collapsed is None:
        return None
    excerpt = collapsed[:FAULT_TEXT_LIMIT]
    if _matches_credential_shape(excerpt):
        return None
    return excerpt
