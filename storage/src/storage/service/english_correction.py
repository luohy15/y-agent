"""English correction service: CRUD, eligibility filter, pending scan, watermark."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from storage.database.base import get_db
from storage.dto.english_correction import EnglishCorrection
from storage.entity.chat import ChatEntity
from storage.repository import english_correction as correction_repo
from storage.service import user_preference as user_pref_service
from storage.util import generate_id, get_unix_timestamp

WATERMARK_KEY = "english_correction_scan"
DEFAULT_LIMIT = 50
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


def is_eligible(
    message: Dict[str, Any],
    *,
    min_words: int = DEFAULT_MIN_WORDS,
    english_ratio: float = DEFAULT_ENGLISH_RATIO,
) -> Tuple[bool, str]:
    """Return (eligible, reason). reason is 'ok' when eligible, else a skip code."""
    if message.get("role") != "user":
        return False, "not_user"
    if not message.get("id"):
        return False, "missing_id"

    text = _message_text(message)
    stripped = text.strip()

    if _TRACE_PREFIX_RE.match(stripped):
        return False, "trace_prefix"
    if _ROUTINE_PREFIX_RE.match(stripped):
        return False, "routine_prefix"
    if stripped == MANAGER_BOOTSTRAP:
        return False, "bootstrap"

    non_prose, reason = _is_non_prose(text)
    if non_prose:
        return False, reason or "non_prose"

    # Majority-language check before min-words: pure-CJK messages have zero
    # ASCII "words" and would otherwise always report too_short.
    if _english_ratio(text) < english_ratio:
        return False, "majority_non_english"

    words = _WORD_RE.findall(text)
    if len(words) < min_words:
        return False, "too_short"

    return True, "ok"


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
    """
    since = _resolve_since(user_id, since_unix)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 500))

    candidates: List[Dict[str, Any]] = []
    with get_db() as session:
        chats = (
            session.query(ChatEntity)
            .filter(
                ChatEntity.user_id == user_id,
                ChatEntity.updated_at_unix >= since,
            )
            .all()
        )
        for chat in chats:
            try:
                raw = json.loads(chat.json_content or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, list):
                continue
            for msg in raw:
                if not isinstance(msg, dict):
                    continue
                eligible, _reason = is_eligible(msg)
                if not eligible:
                    continue
                ts = msg.get("unix_timestamp")
                if ts is None:
                    continue
                ts = int(ts)
                if ts <= since:
                    continue
                message_id = msg.get("id")
                if not message_id:
                    continue
                # Skip messages already corrected
                if correction_repo.find_by_message(user_id, chat.chat_id, message_id):
                    continue
                candidates.append(
                    {
                        "chat_id": chat.chat_id,
                        "message_id": message_id,
                        "message_at": msg.get("timestamp") or "",
                        "message_at_unix": ts,
                        "text": _message_text(msg),
                    }
                )

    candidates.sort(key=lambda m: m["message_at_unix"])
    batch = candidates[:limit]
    if batch:
        scan_through = max(m["message_at_unix"] for m in batch)
    else:
        scan_through = since

    return {
        "messages": batch,
        "scan_through_unix": scan_through,
        "since_unix": since,
    }
