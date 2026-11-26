"""Shared `/<chat_id>` and `/<todo_id>` routes for gateway inbound channels."""

import re
from typing import NamedTuple, Optional

_CHAT_ID_RE = re.compile(r"[0-9a-f]{6}")
_CHAT_ROUTE_RE = re.compile(r"^/([0-9a-f]{6})\s+")
_TODO_ROUTE_RE = re.compile(r"^/(\d+)\s+")


class InboundRoute(NamedTuple):
    """One parsed inbound slash prefix: `kind` is `chat`, `todo`, or None."""

    kind: Optional[str]
    ref: Optional[str]
    body: str


def _leading_quote_end(text: str) -> int:
    """Index after a leading `>` blockquote, or 0 when the text has none.

    Blank lines are part of the block only after the first quote line, so the
    blank line between a quote and the typed reply is skipped too.
    """
    offset = 0
    length = len(text)
    consumed_quote = False
    while offset < length:
        newline = text.find("\n", offset)
        line_end = length if newline < 0 else newline
        stripped = text[offset:line_end].strip()
        if stripped.startswith(">"):
            consumed_quote = True
            offset = length if newline < 0 else newline + 1
            continue
        if stripped == "" and consumed_quote:
            offset = length if newline < 0 else newline + 1
            continue
        break
    return offset if consumed_quote else 0


def split_chat_route(text, skip_leading_quotes=False):
    """Return `(chat_id, body)` when `text` starts with `/<6 hex><whitespace>`.

    The match is anchored at the start. With `skip_leading_quotes`, leading
    `>` lines (a quoted prompt the bridge prepended) are skipped while looking
    for that prefix and kept ahead of the body. A miss returns `(None, text)`.
    """
    if not isinstance(text, str):
        return None, text
    start = _leading_quote_end(text) if skip_leading_quotes else 0
    head = text[start:]
    match = _CHAT_ROUTE_RE.match(head)
    if not match:
        return None, text
    body = head[match.end():]
    if start:
        body = text[:start] + body
    return match.group(1), body


def split_inbound_route(text, skip_leading_quotes=False):
    """Parse `/<chat_id>` or `/<todo_id>` from the start of `text`.

    A 6-hex chat id wins over an all-decimal todo id, matching the historical
    precedence. Both prefixes require trailing whitespace. With
    `skip_leading_quotes`, leading `>` lines are skipped while looking for the
    prefix and kept ahead of the body. A miss returns `(None, None, text)`.
    """
    if not isinstance(text, str):
        return InboundRoute(None, None, text)
    start = _leading_quote_end(text) if skip_leading_quotes else 0
    head = text[start:]
    for kind, pattern in (("chat", _CHAT_ROUTE_RE), ("todo", _TODO_ROUTE_RE)):
        match = pattern.match(head)
        if not match:
            continue
        body = head[match.end():]
        if start:
            body = text[:start] + body
        return InboundRoute(kind, match.group(1), body)
    return InboundRoute(None, None, text)


def format_chat_route(chat_id, text):
    """Prefix `text` with `/<chat_id> ` once. The same id is left unchanged."""
    if not isinstance(chat_id, str) or not _CHAT_ID_RE.fullmatch(chat_id):
        raise ValueError("chat_id must be 6 lowercase hex characters")
    raw = text if isinstance(text, str) else ""
    found, _body = split_chat_route(raw)
    if found == chat_id:
        return raw
    return f"/{chat_id} {raw}"
