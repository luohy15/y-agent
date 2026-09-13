"""Opt-in truncation of large tool-result message content (todo 3515).

Units are Python str code points. Absent `tool_content_limit` is a no-op so
legacy snapshot/SSE payloads stay field-for-field identical.
"""

from typing import Any, Iterable, Optional

TOOL_CONTENT_LIMIT_MIN = 0
TOOL_CONTENT_LIMIT_MAX = 1_000_000


def _tool_call_id(msg: Any) -> str:
    if isinstance(msg, dict):
        tid = msg.get("tool_call_id")
    else:
        tid = getattr(msg, "tool_call_id", None)
    if not tid:
        return ""
    return tid if isinstance(tid, str) else str(tid)


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("role") or ""
    return getattr(msg, "role", None) or ""


def duplicate_tool_call_ids(messages: Iterable[Any]) -> set[str]:
    """tool_call_id values that appear on more than one role=tool message.

    Truncating those would make full output unretrievable: the content route
    409s when an id matches more than one message.
    """
    counts: dict[str, int] = {}
    for msg in messages:
        if _role(msg) != "tool":
            continue
        tid = _tool_call_id(msg)
        if not tid:
            continue
        counts[tid] = counts.get(tid, 0) + 1
    return {tid for tid, n in counts.items() if n > 1}


def truncate_tool_content(
    data: dict,
    limit: Optional[int],
    duplicate_ids: Optional[set[str]] = None,
) -> dict:
    """Return `data` unchanged unless this is a uniquely addressable long tool result."""
    if limit is None:
        return data
    if data.get("role") != "tool":
        return data
    tid = _tool_call_id(data)
    if not tid:
        return data
    if duplicate_ids and tid in duplicate_ids:
        return data
    content = data.get("content")
    if not isinstance(content, str):
        return data
    length = len(content)
    if length <= limit:
        return data
    truncated = dict(data)
    truncated["content"] = content[:limit] + f"\n[truncated: {length} characters total]"
    truncated["content_truncated"] = True
    truncated["content_length"] = length
    return truncated


def apply_tool_content_limit(message_dicts: list[dict], limit: Optional[int]) -> list[dict]:
    if limit is None:
        return message_dicts
    dupes = duplicate_tool_call_ids(message_dicts)
    return [truncate_tool_content(msg, limit, dupes) for msg in message_dicts]
