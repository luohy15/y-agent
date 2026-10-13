"""Recover a usable RSS/Atom entry body from staged feed XML (todo 3900).

The staged `rss/<feed_id>.xml` is re-parsed at download time. A link-level item
uses that body when it is long enough and not truncated; otherwise the caller
page-fetches.
"""

import re
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup
from markdownify import markdownify

from storage.repository.link import strip_query


CONTENT_MIN_CHARS = 200
SUMMARY_MIN_CHARS = 1500

_TRUNCATION_SUFFIXES = ("[…]", "[...]", "…", "...")
_TRUNCATION_PHRASES = ("read more", "continue reading")


def index_feed_entries(xml_bytes: bytes) -> dict:
    """Map each entry's query-stripped link to the feedparser entry.

    Invalid or empty XML returns {}. The first entry wins when two items share
    a base URL.
    """
    if not xml_bytes:
        return {}
    try:
        parsed = feedparser.parse(xml_bytes)
    except Exception:
        return {}
    if getattr(parsed, "bozo", False) and not parsed.entries:
        return {}
    index: dict = {}
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        key = strip_query(link)
        if key not in index:
            index[key] = entry
    return index


def _plain_text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def _is_truncated(text: str) -> bool:
    stripped = text.rstrip()
    if any(stripped.endswith(suffix) for suffix in _TRUNCATION_SUFFIXES):
        return True
    tail = stripped[-200:].lower()
    return any(phrase in tail for phrase in _TRUNCATION_PHRASES)


def _resolve_relative_urls(html: str, base_url: str) -> str:
    """Resolve img src and a href against the entry link.

    feedparser only resolves relatives when the document has xml:base or a
    fetched URL. Staged XML has neither, so do it here before markdownify.
    """
    if not html or not base_url:
        return html or ""
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    root = soup.div
    for tag, attr in (("img", "src"), ("a", "href")):
        for node in root.find_all(tag):
            value = node.get(attr)
            if not isinstance(value, str) or not value.strip():
                continue
            node[attr] = urljoin(base_url, value.strip())
    return root.decode_contents()


def _usable(html: str, minimum: int) -> bool:
    text = _plain_text(html)
    return len(text) >= minimum and not _is_truncated(text)


def _pick_content_html(entry) -> str | None:
    contents = entry.get("content") or []
    if not isinstance(contents, list):
        return None
    html = None
    fallback = None
    for item in contents:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or ""
        if not value.strip():
            continue
        ctype = (item.get("type") or "").lower()
        if "html" in ctype and html is None:
            html = value
        elif fallback is None:
            fallback = value
    return html if html is not None else fallback


def select_feed_body(entry) -> str | None:
    """Return usable entry HTML, or None when the caller should page-fetch.

    Prefer `entry.content` (Atom content / RSS content:encoded) at
    CONTENT_MIN_CHARS. Otherwise `entry.summary` at SUMMARY_MIN_CHARS.
    """
    base_url = entry.get("link") or ""
    content = _pick_content_html(entry)
    if content and _usable(content, CONTENT_MIN_CHARS):
        return _resolve_relative_urls(content, base_url)
    summary = entry.get("summary") or ""
    if summary and _usable(summary, SUMMARY_MIN_CHARS):
        return _resolve_relative_urls(summary, base_url)
    return None


def feed_markdown(title: str | None, url: str, html: str) -> str:
    """Match the page-fetch content.md header, with an HTML body as markdown."""
    body = markdownify(html or "", heading_style="ATX")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    heading = title or url
    return f"# {heading}\n\n- **Link**: {url}\n\n---\n\n{body}"
