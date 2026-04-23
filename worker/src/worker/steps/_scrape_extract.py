"""Shared CSS-selector based HTML scrape helpers used by fetch_rss_xml."""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger


async def fetch_html(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        resp = await client.get(url, follow_redirects=True)
    except Exception as e:
        logger.error("scrape fetch error for {}: {}", url, e)
        return None
    if resp.status_code >= 400:
        logger.error("scrape HTTP {} for {}", resp.status_code, url)
        return None
    return resp.text


def parse_scrape_date(raw: Optional[str], date_format: Optional[str]) -> Optional[int]:
    """Parse a date string into epoch ms. Returns None on failure."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    dt: Optional[datetime] = None
    if date_format:
        try:
            dt = datetime.strptime(text, date_format)
        except ValueError as e:
            logger.warning("scrape date parse strptime failed: value={!r} fmt={!r} err={}", text, date_format, e)
            return None
    else:
        iso_text = text.replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(iso_text)
        except ValueError as e:
            logger.warning("scrape date parse isoformat failed: value={!r} err={}", text, e)
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def extract_scrape_items(feed, html: str) -> list[dict]:
    """Apply scrape_config selectors to HTML. Returns list of {url, title, published_at}."""
    config = feed.scrape_config or {}
    item_selector = config.get('item_selector')
    if not item_selector:
        return []

    title_selector = config.get('title_selector')
    link_selector = config.get('link_selector')
    link_attr = config.get('link_attr') or 'href'
    date_selector = config.get('date_selector')
    date_attr = config.get('date_attr')
    date_format = config.get('date_format')
    date_text_mode = config.get('date_text_mode') or 'all'

    soup = BeautifulSoup(html, 'lxml')
    items = []
    seen_urls = set()

    for node in soup.select(item_selector):
        link_node = node.select_one(link_selector) if link_selector else node
        if link_node is None:
            continue
        href = link_node.get(link_attr)
        if not href:
            continue
        url = urljoin(feed.url, href.strip())
        if url in seen_urls:
            continue
        seen_urls.add(url)

        if title_selector:
            title_node = node.select_one(title_selector)
            title = title_node.get_text(strip=True) if title_node else None
        else:
            title = node.get_text(strip=True) or None

        published_at: Optional[int] = None
        if date_selector:
            date_node = node.select_one(date_selector)
            if date_node is not None:
                if date_attr:
                    raw = date_node.get(date_attr)
                elif date_text_mode == 'direct':
                    raw = ''.join(date_node.find_all(string=True, recursive=False)).strip()
                else:
                    raw = date_node.get_text(strip=True)
                published_at = parse_scrape_date(raw, date_format)

        items.append({"url": url, "title": title, "published_at": published_at})

    return items
