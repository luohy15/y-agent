"""English correction service: CRUD, eligibility filter, pending scan, watermark."""

from __future__ import annotations

import heapq
import json
import re
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from storage.database.base import get_db
from storage.dto.english_correction import EnglishCorrection
from storage.entity.chat import ChatEntity
from storage.repository import english_correction as correction_repo
from storage.service import user_preference as user_pref_service
from storage.util import generate_id, get_unix_timestamp

WATERMARK_KEY = "english_correction_scan"
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
CHAT_STREAM_BATCH = 20  # chats pulled per round-trip while streaming the scan
DEFAULT_BOOTSTRAP_LOOKBACK_MS = 60 * 60 * 1000  # 1 hour
DEFAULT_MIN_WORDS = 5
DEFAULT_ENGLISH_RATIO = 0.6
MANAGER_BOOTSTRAP = "load manager skill"

# Non-prose heuristics
_FENCED_CODE_RE = re.compile(r"```")
_SHELL_LINE_RE = re.compile(r"^\s*[\$#>]\s+\S+", re.MULTILINE)
_PATH_LINE_RE = re.compile(
    r"^\s*(?:/[A-Za-z0-9._\-/]+|[A-Za-z]:\\[A-Za-z0-9._\\\-]+|~/?[A-Za-z0-9._\-/]*)\s*$",
    re.MULTILINE,
)
_TRACE_PREFIX_RE = re.compile(r"^\s*\[trace:")
_ROUTINE_PREFIX_RE = re.compile(r"^\s*\[routine:")
_UI_WRAPPER_TAG_RE = re.compile(
    r"<\s*(/?)\s*(selection|instruction)\b[^>]*>",
    re.IGNORECASE,
)
_UI_WRAPPER_MARKER_RE = re.compile(
    r"<\s*/?\s*(?:selection|instruction)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_SYMBOL_RE = re.compile(r"[^\w\s\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", re.UNICODE)


def add_correction(
    user_id: int,
    chat_id: str,
    message_id: str,
    message_at: str,
    message_at_unix: int,
    original_text: str,
    corrected_text: str,
    error_categories: List[str],
    explanation: str,
) -> EnglishCorrection:
    """Insert a correction. On duplicate (chat_id, message_id) return the existing row."""
    existing = correction_repo.find_by_message(user_id, chat_id, message_id)
    if existing:
        return existing
    correction = EnglishCorrection(
        correction_id=generate_id(),
        chat_id=chat_id,
        message_id=message_id,
        message_at=message_at,
        message_at_unix=int(message_at_unix),
        original_text=original_text,
        corrected_text=corrected_text,
        error_categories=list(error_categories or []),
        explanation=explanation,
        dismissed=False,
    )
    return correction_repo.save_correction(user_id, correction)


def dismiss_correction(user_id: int, correction_id: str) -> Optional[EnglishCorrection]:
    correction = correction_repo.get_correction(user_id, correction_id)
    if not correction:
        return None
    correction.dismissed = True
    return correction_repo.save_correction(user_id, correction)


def get_correction(user_id: int, correction_id: str) -> Optional[EnglishCorrection]:
    return correction_repo.get_correction(user_id, correction_id)


def list_corrections(
    user_id: int,
    dismissed: Optional[bool] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[EnglishCorrection]:
    return correction_repo.list_corrections(
        user_id,
        dismissed=dismissed,
        category=category,
        query=query,
        limit=limit,
        offset=offset,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
    )


# ---------------------------------------------------------------------------
# Eligibility filter
# ---------------------------------------------------------------------------

def _message_text(message: Dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", "") or ""))
        return "".join(parts)
    return str(content or "")


def _strip_ui_wrapper_blocks(text: str) -> Optional[str]:
    marker_starts = [match.start() for match in _UI_WRAPPER_MARKER_RE.finditer(text)]
    if not marker_starts:
        return text

    tags = list(_UI_WRAPPER_TAG_RE.finditer(text))
    if marker_starts != [match.start() for match in tags]:
        return None

    parts: List[str] = []
    stack: List[str] = []
    cursor = 0
    for tag in tags:
        closing = bool(tag.group(1))
        name = tag.group(2).lower()
        if not stack:
            parts.append(text[cursor:tag.start()])
        if closing:
            if not stack or stack[-1] != name:
                return None
            stack.pop()
            if not stack:
                parts.append(" ")
                cursor = tag.end()
        else:
            stack.append(name)

    if stack:
        return None
    parts.append(text[cursor:])
    return "".join(parts).strip()


def _is_non_prose(text: str) -> Tuple[bool, Optional[str]]:
    stripped = text.strip()
    if not stripped:
        return True, "empty"
    if _FENCED_CODE_RE.search(stripped):
        return True, "code_block"
    # Whole-message shell command (single short line starting with $/#/>)
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) == 1 and _SHELL_LINE_RE.match(lines[0]):
        return True, "shell"
    if len(lines) == 1 and _PATH_LINE_RE.match(lines[0]):
        return True, "path"
    # High symbol ratio across non-whitespace chars
    non_ws = re.sub(r"\s+", "", stripped)
    if non_ws:
        symbols = len(_SYMBOL_RE.findall(non_ws))
        if symbols / len(non_ws) > 0.4 and len(non_ws) >= 10:
            return True, "symbol_ratio"
    return False, None


def _english_ratio(text: str) -> float:
    ascii_letters = len(_ASCII_LETTER_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    total = ascii_letters + cjk
    if total == 0:
        return 0.0
    return ascii_letters / total


def _eligible_text(
    message: Dict[str, Any],
    *,
    min_words: int = DEFAULT_MIN_WORDS,
    english_ratio: float = DEFAULT_ENGLISH_RATIO,
) -> Tuple[Optional[str], str]:
    if message.get("role") != "user":
        return None, "not_user"
    if not message.get("id"):
        return None, "missing_id"

    text = _strip_ui_wrapper_blocks(_message_text(message))
    if text is None:
        return None, "malformed_ui_wrapper"
    stripped = text.strip()

    if _TRACE_PREFIX_RE.match(stripped):
        return None, "trace_prefix"
    if _ROUTINE_PREFIX_RE.match(stripped):
        return None, "routine_prefix"
    if stripped == MANAGER_BOOTSTRAP:
        return None, "bootstrap"

    non_prose, reason = _is_non_prose(text)
    if non_prose:
        return None, reason or "non_prose"

    # Majority-language check before min-words: pure-CJK messages have zero
    # ASCII "words" and would otherwise always report too_short.
    if _english_ratio(text) < english_ratio:
        return None, "majority_non_english"

    words = _WORD_RE.findall(text)
    if len(words) < min_words:
        return None, "too_short"

    return text, "ok"


def is_eligible(
    message: Dict[str, Any],
    *,
    min_words: int = DEFAULT_MIN_WORDS,
    english_ratio: float = DEFAULT_ENGLISH_RATIO,
) -> Tuple[bool, str]:
    """Return (eligible, reason). reason is 'ok' when eligible, else a skip code."""
    text, reason = _eligible_text(
        message,
        min_words=min_words,
        english_ratio=english_ratio,
    )

    return text is not None, reason


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

def get_watermark(user_id: int) -> Optional[int]:
    pref = user_pref_service.get_preference(user_id, WATERMARK_KEY)
    if not pref or pref.value is None:
        return None
    value = pref.value
    if isinstance(value, dict):
        ts = value.get("scanned_through_unix")
        return int(ts) if ts is not None else None
    return None


def set_watermark(user_id: int, scanned_through_unix: int) -> Dict[str, int]:
    payload = {"scanned_through_unix": int(scanned_through_unix)}
    user_pref_service.upsert_preference(user_id, WATERMARK_KEY, payload)
    return payload


def _resolve_since(user_id: int, since_unix: Optional[int]) -> int:
    if since_unix is not None:
        return int(since_unix)
    watermark = get_watermark(user_id)
    if watermark is not None:
        return watermark
    return get_unix_timestamp() - DEFAULT_BOOTSTRAP_LOOKBACK_MS


# ---------------------------------------------------------------------------
# Pending scan
# ---------------------------------------------------------------------------

def _iter_chat_messages(json_content: Optional[str]) -> Iterator[Dict[str, Any]]:
    """Yield message dicts out of a persisted `chat.json_content` blob.

    The blob is `json.dumps(Chat.to_dict())`, i.e. an object with a `messages`
    key. A bare list is also accepted so hand-built fixtures keep working.
    """
    try:
        raw = json.loads(json_content or "{}")
    except (TypeError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        raw = raw.get("messages")
    if not isinstance(raw, list):
        return
    for msg in raw:
        if isinstance(msg, dict):
            yield msg


def _iter_candidates(
    chat_id: str,
    json_content: Optional[str],
    since: int,
    already_corrected: Set[Tuple[str, str]],
) -> Iterator[Dict[str, Any]]:
    for msg in _iter_chat_messages(json_content):
        ts = msg.get("unix_timestamp")
        if ts is None:
            continue
        ts = int(ts)
        if ts <= since:
            continue
        message_id = msg.get("id")
        if not message_id:
            continue
        if (chat_id, message_id) in already_corrected:
            continue
        text, _reason = _eligible_text(msg)
        if text is None:
            continue
        yield {
            "chat_id": chat_id,
            "message_id": message_id,
            "message_at": msg.get("timestamp") or "",
            "message_at_unix": ts,
            "text": text,
        }


def list_pending(
    user_id: int,
    since_unix: Optional[int] = None,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Return eligible user messages after the watermark (or bootstrap lookback).

    Shape:
      {
        "messages": [{chat_id, message_id, message_at, message_at_unix, text}, ...],
        "scan_through_unix": <max unix in batch or since>,
        "since_unix": <resolved lower bound>,
      }
    Messages already stored as corrections are excluded.

    Memory is bounded regardless of how wide `since_unix` is: chats are streamed
    one batch at a time (only `chat_id` + `json_content`, no ORM identity map)
    and only the oldest `limit` candidates are kept, so an arbitrarily large
    window costs one chat blob plus `limit` rows.
    """
    since = _resolve_since(user_id, since_unix)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    # One bounded query for the dedup keys, instead of a lookup per candidate.
    already_corrected = correction_repo.list_message_keys(user_id, since_unix=since)

    # Max-heap (negated timestamp) capped at `limit`, so the newest candidate is
    # the one evicted once the batch is full.
    heap: List[Tuple[int, int, Dict[str, Any]]] = []
    seq = 0
    with get_db() as session:
        rows = (
            session.query(ChatEntity.chat_id, ChatEntity.json_content)
            .filter(
                ChatEntity.user_id == user_id,
                ChatEntity.updated_at_unix >= since,
            )
            .yield_per(CHAT_STREAM_BATCH)
        )
        for chat_id, json_content in rows:
            for candidate in _iter_candidates(chat_id, json_content, since, already_corrected):
                seq += 1
                heapq.heappush(heap, (-candidate["message_at_unix"], seq, candidate))
                if len(heap) > limit:
                    heapq.heappop(heap)

    batch = [item[2] for item in heap]
    batch.sort(key=lambda m: m["message_at_unix"])
    scan_through = batch[-1]["message_at_unix"] if batch else since

    return {
        "messages": batch,
        "scan_through_unix": scan_through,
        "since_unix": since,
    }
