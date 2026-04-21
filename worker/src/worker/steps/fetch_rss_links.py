"""Scheduled action: pull new items from every RssFeed into the link table.

Mirrors alpha_vantage_news's step1_symbol_checker: acquires a pipeline lock,
concurrently fetches feed XML, parses with feedparser, and writes new
LinkEntity/LinkActivityEntity rows tagged with source='rss'.

Also supports scrape-type feeds: GET the URL, apply CSS selectors via
BeautifulSoup, and write each matched item into the link table with
source='rss' + source_feed_id. Dedup by LinkEntity.base_url existence since
scraped items have no authoritative publish timestamp.
"""

import asyncio
import calendar
import os
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from storage.repository import link as link_repo
from storage.service import link as link_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import rss_feed as rss_feed_service


LOCK_NAME = "fetch_rss_links"


def _parse_feed_timestamp(entry) -> Optional[int]:
    ts_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not ts_struct:
        return None
    return int(calendar.timegm(ts_struct) * 1000)


async def _fetch_xml(client: httpx.AsyncClient, url: str) -> Optional[bytes]:
    try:
        resp = await client.get(url, follow_redirects=True)
    except Exception as e:
        logger.error("fetch_rss_links fetch error for {}: {}", url, e)
        return None
    if resp.status_code >= 400:
        logger.error("fetch_rss_links HTTP {} for {}", resp.status_code, url)
        return None
    return resp.content


def _ingest_entries(user_id: int, feed, parsed) -> tuple[int, int]:
    """Insert new items into the link table. Returns (added, max_ts)."""
    last_item_ts = feed.last_item_ts or 0
    max_ts = last_item_ts
    added = 0

    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        ts_ms = _parse_feed_timestamp(entry)
        if ts_ms is None or ts_ms <= last_item_ts:
            continue

        title = entry.get("title")
        activity = link_service.add_link(
            user_id, url, title=title, timestamp=ts_ms, published_at=ts_ms,
        )
        link_repo.set_link_source_if_null(activity.link_id, "rss", feed.rss_feed_id)
        added += 1
        if ts_ms > max_ts:
            max_ts = ts_ms

    return added, max_ts


async def _process_feed(client: httpx.AsyncClient, user_id: int, feed) -> dict:
    if (feed.feed_type or 'rss') == 'scrape':
        return await _process_scrape_feed(client, user_id, feed)

    xml = await _fetch_xml(client, feed.url)
    if xml is None:
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": "fetch failed"}

    parsed = feedparser.parse(xml)
    if parsed.bozo and not parsed.entries:
        err = str(parsed.bozo_exception)
        logger.error("fetch_rss_links parse error feed={}: {}", feed.rss_feed_id, err)
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": err}

    added, max_ts = _ingest_entries(user_id, feed, parsed)
    now_iso = datetime.now(timezone.utc).isoformat()
    rss_feed_service.update_fetch_state(
        feed.rss_feed_id,
        last_fetched_at=now_iso,
        last_item_ts=max_ts if max_ts > (feed.last_item_ts or 0) else None,
    )
    logger.info("fetch_rss_links feed={} user={} added={}", feed.rss_feed_id, user_id, added)
    return {"feed_id": feed.rss_feed_id, "added": added}


async def _fetch_html(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        resp = await client.get(url, follow_redirects=True)
    except Exception as e:
        logger.error("fetch_rss_links scrape fetch error for {}: {}", url, e)
        return None
    if resp.status_code >= 400:
        logger.error("fetch_rss_links scrape HTTP {} for {}", resp.status_code, url)
        return None
    return resp.text


def _extract_scrape_items(feed, html: str) -> list[dict]:
    """Apply scrape_config selectors to HTML. Returns list of {url, title}."""
    config = feed.scrape_config or {}
    item_selector = config.get('item_selector')
    if not item_selector:
        return []

    title_selector = config.get('title_selector')
    link_selector = config.get('link_selector')
    link_attr = config.get('link_attr') or 'href'

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

        items.append({"url": url, "title": title})

    return items


async def _process_scrape_feed(client: httpx.AsyncClient, user_id: int, feed) -> dict:
    if not feed.scrape_config or not feed.scrape_config.get('item_selector'):
        logger.error("fetch_rss_links scrape feed={} missing item_selector", feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": "missing item_selector"}

    html = await _fetch_html(client, feed.url)
    if html is None:
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": "fetch failed"}

    try:
        items = _extract_scrape_items(feed, html)
    except Exception as e:
        logger.exception("fetch_rss_links scrape feed={} parse error", feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": f"parse error: {e}"}

    if not items:
        now_iso = datetime.now(timezone.utc).isoformat()
        rss_feed_service.update_fetch_state(feed.rss_feed_id, last_fetched_at=now_iso)
        logger.info("fetch_rss_links scrape feed={} user={} added=0 (no items matched)", feed.rss_feed_id, user_id)
        return {"feed_id": feed.rss_feed_id, "added": 0}

    urls = [it["url"] for it in items]
    existing = {e.base_url for e in link_repo.get_links_by_urls(urls)}

    now_ms = int(time.time() * 1000)
    added = 0
    max_ts = feed.last_item_ts or 0

    for idx, it in enumerate(items):
        base_url = it["url"].split('?')[0].split('#')[0]
        if base_url in existing:
            continue
        ts_ms = now_ms + idx
        activity = link_service.add_link(user_id, it["url"], title=it["title"], timestamp=ts_ms)
        link_repo.set_link_source_if_null(activity.link_id, "rss", feed.rss_feed_id)
        added += 1
        if ts_ms > max_ts:
            max_ts = ts_ms

    now_iso = datetime.now(timezone.utc).isoformat()
    rss_feed_service.update_fetch_state(
        feed.rss_feed_id,
        last_fetched_at=now_iso,
        last_item_ts=max_ts if max_ts > (feed.last_item_ts or 0) else None,
    )
    logger.info("fetch_rss_links scrape feed={} user={} matched={} added={}",
                feed.rss_feed_id, user_id, len(items), added)
    return {"feed_id": feed.rss_feed_id, "added": added}


async def handle_fetch_rss_links() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("fetch_rss_links: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        feeds = rss_feed_service.list_all_feeds()
        logger.info("fetch_rss_links: scanning {} feeds", len(feeds))
        if not feeds:
            return {"status": "ok", "action": LOCK_NAME, "feeds": 0, "items": 0}

        rate_limit = int(os.environ.get("RSS_FETCH_RATE_LIMIT", 10))
        semaphore = asyncio.Semaphore(rate_limit)
        timeout = int(os.environ.get("RSS_FETCH_TIMEOUT", 20))

        async with httpx.AsyncClient(timeout=timeout) as client:
            async def guarded(user_id, feed):
                async with semaphore:
                    try:
                        return await _process_feed(client, user_id, feed)
                    except Exception as e:
                        logger.exception("fetch_rss_links feed={} unexpected error", feed.rss_feed_id)
                        return {"feed_id": feed.rss_feed_id, "added": 0, "error": str(e)}

            results = await asyncio.gather(
                *(guarded(user_id, feed) for user_id, feed in feeds)
            )

        total_items = sum(r.get("added", 0) for r in results)
        errors = [r for r in results if r.get("error")]
        out = {"status": "ok", "action": LOCK_NAME, "feeds": len(feeds), "items": total_items}
        if errors:
            out["errors"] = errors
        return out
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
