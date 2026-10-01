"""Opt-in truncation of large tool-result message content (todo 3515).

Units are Python str code points. Absent `tool_content_limit` is a no-op so
legacy snapshot/SSE payloads stay field-for-field identical.
"""

import json
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


def assistant_tool_call_arguments(messages: Iterable[Any]) -> dict[str, Any]:
    """tool_call id -> parsed `function.arguments` for ids seen exactly once.

    Ids that repeat across assistant tool_calls, or whose arguments do not
    parse, are left out so their tool messages keep `arguments`.
    """
    parsed: dict[str, Any] = {}
    seen: set[str] = set()
    bad: set[str] = set()
    for msg in messages:
        if isinstance(msg, dict):
            if msg.get("role") != "assistant":
                continue
            calls = msg.get("tool_calls")
        else:
            if getattr(msg, "role", None) != "assistant":
                continue
            calls = getattr(msg, "tool_calls", None)
        for call in calls or []:
            if not isinstance(call, dict):
                continue
            cid = call.get("id")
            if not cid or not isinstance(cid, str):
                continue
            if cid in seen:
                bad.add(cid)
                continue
            seen.add(cid)
            fn = call.get("function")
            raw = fn.get("arguments") if isinstance(fn, dict) else None
            try:
                parsed[cid] = json.loads(raw)
            except (TypeError, ValueError):
                bad.add(cid)
    for cid in bad:
        parsed.pop(cid, None)
    return parsed


def drop_duplicate_tool_arguments(
    data: dict,
    call_arguments: dict[str, Any],
    duplicate_ids: Optional[set[str]] = None,
) -> dict:
    """Drop role=tool `arguments` when the matching assistant tool_call carries the same value."""
    if data.get("role") != "tool" or "arguments" not in data:
        return data
    tid = _tool_call_id(data)
    if not tid or (duplicate_ids and tid in duplicate_ids):
        return data
    if tid not in call_arguments or call_arguments[tid] != data["arguments"]:
        return data
    slim = dict(data)
    del slim["arguments"]
    return slim


def apply_tool_content_limit(message_dicts: list[dict], limit: Optional[int]) -> list[dict]:
    if limit is None:
        return message_dicts
    dupes = duplicate_tool_call_ids(message_dicts)
    call_args = assistant_tool_call_arguments(message_dicts)
    return [
        drop_duplicate_tool_arguments(truncate_tool_content(msg, limit, dupes), call_args, dupes)
        for msg in message_dicts
    ]
