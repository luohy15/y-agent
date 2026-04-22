import os
import re
import time
from typing import List
from loguru import logger

def get_unix_timestamp() -> int:
    """Get current time as 13-digit unix timestamp (milliseconds)"""
    return int(time.time() * 1000)

def get_utc_iso8601_timestamp() -> str:
    """Get current UTC time as ISO 8601 string with ms precision and Z suffix.
    Example: '2025-04-28T04:08:29.568Z'
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

def generate_id() -> str:
    """Generate a unique ID (6 hex characters)."""
    import uuid
    return uuid.uuid4().hex[:6]

_BASE62_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

def generate_long_id(length: int = 22) -> str:
    """Generate a URL-safe base62 ID.

    Uses base62 characters (a-z, A-Z, 0-9) for compact, readable IDs.
    22 characters provides ~131 bits of entropy (62^22 ≈ 2^131).
    """
    import secrets
    return ''.join(secrets.choice(_BASE62_CHARS) for _ in range(length))

def generate_message_id() -> str:
    """Generate a unique message ID in format msg_{timestamp}_{random8chars}"""
    import random
    import string
    chars = string.ascii_lowercase + string.digits
    rand = ''.join(random.choices(chars, k=8))
    return f"msg_{int(time.time() * 1000)}_{rand}"


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown to Telegram-compatible HTML.

    Telegram HTML supports: <b>, <i>, <s>, <code>, <pre>, <a>.
    Unsupported elements (headings, lists, tables, etc.) are converted to
    readable plain-text equivalents using regex.
    """
    placeholders = []

    def _add_placeholder(html: str) -> str:
        idx = len(placeholders)
        placeholders.append(html)
        return f"\x00PH{idx}\x00"

    # Fenced code blocks: ```lang\n...\n``` (protect from further processing)
    def _sub_pre(m):
        code = m.group(1)
        escaped = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return _add_placeholder(f"<pre>{escaped}</pre>")
    text = re.sub(r'```(?:\w*)\n([\s\S]*?)```', _sub_pre, text)

    # Tables: header + separator + rows → aligned monospace block via <pre>
    # Must run before inline code so backticks in cells are preserved as-is.
    def _sub_table(m):
        rows = m.group(0).strip().split('\n')
        parsed = []
        for row in rows:
            if re.match(r'^\|[\s\-:|]+\|$', row):
                continue
            cells = [re.sub(r'`([^`]+)`', r'\1', c.strip()) for c in row.strip('|').split('|')]
            parsed.append(cells)
        if not parsed:
            return m.group(0)
        col_count = max(len(r) for r in parsed)
        widths = [0] * col_count
        for row in parsed:
            for i, cell in enumerate(row):
                if i < col_count:
                    widths[i] = max(widths[i], len(cell))
        lines = []
        for ri, row in enumerate(parsed):
            parts = [row[i].ljust(widths[i]) if i < len(row) else ' ' * widths[i] for i in range(col_count)]
            lines.append(' | '.join(parts))
            if ri == 0:
                lines.append('-+-'.join('-' * w for w in widths))
        table_text = '\n'.join(lines)
        escaped = table_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return _add_placeholder(f"<pre>{escaped}</pre>")
    text = re.sub(r'(?m)(^\|.+\|$\n?){2,}', _sub_table, text)

    # Inline code: `...` (protect from further processing)
    def _sub_code(m):
        code = m.group(1)
        escaped = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return _add_placeholder(f"<code>{escaped}</code>")
    text = re.sub(r'`([^`]+)`', _sub_code, text)

    # --- Line-level syntax (before HTML escaping) ---

    # Headings: # text → **text** (will become <b> later)
    text = re.sub(r'(?m)^#{1,6}\s+(.+)$', r'**\1**', text)

    # Horizontal rules
    text = re.sub(r'(?m)^[\s]*([-*_]){3,}\s*$', '—' * 20, text)

    # Checkboxes (before bullet conversion)
    text = re.sub(r'(?m)^(\s*)[-*]\s+\[x\]\s+', r'\1✅ ', text)
    text = re.sub(r'(?m)^(\s*)[-*]\s+\[ \]\s+', r'\1⬜ ', text)

    # Bullet lists: - item or * item → • item
    text = re.sub(r'(?m)^(\s*)[-*]\s+', lambda m: m.group(1) + '• ', text)

    # Blockquotes: > text → ┃ text
    text = re.sub(r'(?m)^>\s?(.*)$', r'┃ \1', text)

    # --- HTML escape ---
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # --- Inline formatting ---
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Restore placeholders
    for i, ph in enumerate(placeholders):
        text = text.replace(f"\x00PH{i}\x00", ph)

    return text


def get_telegram_bot_token() -> str:
    """Get Telegram bot token from environment."""
    return os.environ.get("TELEGRAM_BOT_TOKEN_DEV", os.getenv("TELEGRAM_BOT_TOKEN", ""))


def send_telegram_message(bot_token: str, chat_id, text: str, message_thread_id=None) -> None:
    """Send a message to Telegram with HTML formatting, chunking, and plain-text fallback."""
    import httpx

    html_text = markdown_to_telegram_html(text)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    MAX_LEN = 4096
    html_chunks = [html_text[i:i + MAX_LEN] for i in range(0, len(html_text), MAX_LEN)]
    plain_chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]

    with httpx.Client() as client:
        for i, chunk in enumerate(html_chunks):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id
            resp = client.post(url, json=payload)
            if not resp.is_success:
                fallback_payload = {"chat_id": chat_id, "text": plain_chunks[i] if i < len(plain_chunks) else chunk}
                if message_thread_id:
                    fallback_payload["message_thread_id"] = message_thread_id
                client.post(url, json=fallback_payload)


def build_message_path(messages: List, message_id: str) -> List:
    """Traverse parent_id from a given message back to root, returning messages forming the conversation path."""
    msg_map = {}
    for msg in messages:
        if msg.id:
            msg_map[msg.id] = msg

    logger.debug("build_message_path: starting from {}, {} messages in map", message_id, len(msg_map))

    path = []
    visited = set()
    current_id = message_id
    max_steps = 20
    while current_id and current_id in msg_map and len(path) < max_steps:
        if current_id in visited:
            logger.warning("build_message_path: cycle detected at {}, breaking", current_id)
            break
        visited.add(current_id)
        msg = msg_map[current_id]
        path.append(msg)
        logger.debug("build_message_path: {} -> parent {}", current_id, msg.parent_id)
        current_id = msg.parent_id

    path.reverse()
    logger.debug("build_message_path: result path has {} messages", len(path))
    return path
