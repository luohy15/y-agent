"""Shared inbound quote context for gateway channels (WeChat and Telegram).

One representation composes the model-visible blockquote: a sender header,
truncated text, and media or unresolved placeholders. Both channels' inbound
handlers go through `format_quoted_message`, so a reply reads the same whether
it came from WeChat or Telegram.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Optional

MAX_QUOTE_CHARS = 500
TRUNCATED = "… [truncated]"
UNRESOLVED = "[Quoted earlier message: content unavailable]"

_MEDIA_LABELS = {
    "image": "[image]",
    "voice": "[voice]",
    "video": "[video]",
    "attachment": "[attachment]",
}


@dataclass(frozen=True)
class QuoteContext:
    """One quote to show above a reply.

    `sender` is `"assistant"` when the quoted message is the bot's own,
    `"you"` when it is the user's, and `None` when the payload does not say.
    `media_kind` is one of `image` / `file` / `voice` / `video` /
    `attachment`; `unresolved` marks an ID-only quote whose content is gone.
    """

    text: str = ""
    sender: Optional[str] = None
    media_kind: Optional[str] = None
    media_name: Optional[str] = None
    unresolved: bool = False


def _nth_index(text: str, value: str, occurrence: int, from_index: int = 0) -> int:
    if not value or not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0:
        return -1
    position = from_index
    for current in range(occurrence + 1):
        position = text.find(value, position)
        if position < 0:
            return -1
        if current < occurrence:
            position += len(value)
    return position


def _candidate(full_text: str, partial: Mapping, end_search: str) -> Optional[str]:
    start_token = partial.get("start")
    end_token = partial.get("end")
    if not isinstance(start_token, str) or not isinstance(end_token, str):
        return None
    start = _nth_index(full_text, start_token, partial.get("startindex"))
    if start < 0:
        return None
    end_index = partial.get("endindex")
    if end_search == "global":
        end = _nth_index(full_text, end_token, end_index)
    else:
        end = _nth_index(full_text, end_token, end_index, start + len(start_token))
    if end < start:
        return None
    return full_text[start:end + len(end_token)]


def resolve_partial_quote(full_text: str, partial: Mapping) -> Optional[str]:
    """Resolve the selected substring of a quoted message, or `None`.

    Newer WeChat clients send `partial_text` instead of the whole quote: the
    first and last token of the selection plus their occurrence indexes, read
    either globally or relative to the selection start. Both readings are
    computed and `quotemd5` picks the one that hashes to the client's digest.
    Without a digest the global reading wins, matching the payload examples.
    A miss returns `None` so the caller falls back to the full text.
    """
    if not full_text or not isinstance(partial, Mapping):
        return None
    start_token = partial.get("start")
    end_token = partial.get("end")
    if not isinstance(start_token, str) or not start_token:
        return None
    if not isinstance(end_token, str) or not end_token:
        return None
    candidates = []
    for mode in ("global", "relative"):
        value = _candidate(full_text, partial, mode)
        if value and value not in candidates:
            candidates.append(value)
    expected = str(partial.get("quotemd5") or "").strip().lower()
    if not expected:
        return candidates[0] if candidates else None
    for value in candidates:
        if hashlib.md5(value.encode("utf-8")).hexdigest() == expected:
            return value
    return None


def _media_label(media_kind: str, media_name: Optional[str]) -> str:
    kind = (media_kind or "").strip().lower()
    if kind == "file":
        name = (media_name or "").strip()
        return f"[file: {name}]" if name else "[attachment]"
    return _MEDIA_LABELS.get(kind, "[attachment]")


def _quote_text(quote: QuoteContext) -> Optional[str]:
    text = (quote.text or "").strip()
    label = _media_label(quote.media_kind, quote.media_name) if quote.media_kind else ""
    if label and text:
        return f"{label} {text}"
    return label or text or None


def _truncate(text: str, max_chars: int) -> str:
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + TRUNCATED


def _sender_header(sender: Optional[str]) -> str:
    if sender == "assistant":
        return "[Quoted assistant]"
    if sender == "you":
        return "[Quoted you]"
    return "[Quoted]"


def _leading_blockquote(text: str) -> Optional[str]:
    """Content of the blockquote that starts `text`, or `None` when it has none."""
    collected = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            collected.append(stripped[1:].strip())
            continue
        if not stripped and collected:
            continue
        break
    return "\n".join(collected) if collected else None


def _block(text: str, sender: Optional[str]) -> str:
    header = _sender_header(sender)
    lines = text.splitlines() or [""]
    rendered = [f"> {header}: {lines[0]}"]
    rendered.extend(f"> {line}" for line in lines[1:])
    return "\n".join(rendered)


def _norm(text: str) -> str:
    """Comparison form: per-line trimmed, joined by newlines, outer trimmed."""
    return "\n".join(line.strip() for line in (text or "").splitlines()).strip()


def _block_content(block: str) -> str:
    """The visible text of a rendered blockquote, without the `> ` markers."""
    return _norm("\n".join(line[1:] for line in block.splitlines()))


def _same_quote(seen: str, candidate: str, max_chars: int) -> bool:
    """True when two quoted texts are identical, allowance for truncation."""
    seen, candidate = _norm(seen), _norm(candidate)
    if seen == candidate:
        return True
    return _truncate(seen, max_chars) == _truncate(candidate, max_chars)


def format_quoted_message(body: str, quote: Optional[QuoteContext], max_chars: int = MAX_QUOTE_CHARS) -> str:
    """Prepend `quote` to `body` as a blockquote, or return `body` unchanged.

    A blank line separates the quote from the body so CommonMark does not treat
    the next line as a lazy continuation of the blockquote. A body that already
    starts with the identical quote is left alone, so a bridge that still sends
    the old pre-flattened `> ` text does not duplicate it. The check covers a
    headed multi-line quote, a raw quote longer than `max_chars`, and the
    unresolved placeholder.
    """
    if quote is None:
        return body
    existing = _leading_blockquote(body or "")
    if quote.unresolved:
        if existing is not None and _norm(existing) == UNRESOLVED:
            return body
        return f"> {UNRESOLVED}\n\n{body}" if body else f"> {UNRESOLVED}"
    raw = _quote_text(quote)
    if not raw:
        return body
    text = _truncate(raw, max_chars)
    block = _block(text, quote.sender)
    if existing is not None:
        seen = _norm(existing)
        if any(_same_quote(seen, candidate, max_chars) for candidate in (
            raw, _block_content(_block(raw, quote.sender)), text, _block_content(block),
        )):
            return body
    return f"{block}\n\n{body}" if body else block
