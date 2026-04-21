"""Scheduled action: pull new items from every RssFeed into the link table.

Mirrors alpha_vantage_news's step1_symbol_checker: acquires a pipeline lock,
concurrently fetches feed XML, parses with feedparser, and writes new
LinkEntity/LinkActivityEntity rows tagged with source='rss'.
"""

import asyncio
import calendar
import os
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
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
        activity = link_service.add_link(user_id, url, title=title, timestamp=ts_ms)
        link_repo.set_link_source_if_null(activity.link_id, "rss", feed.rss_feed_id)
        added += 1
        if ts_ms > max_ts:
            max_ts = ts_ms

    return added, max_ts


async def _process_feed(client: httpx.AsyncClient, user_id: int, feed) -> dict:
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
