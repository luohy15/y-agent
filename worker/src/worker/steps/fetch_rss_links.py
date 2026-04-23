"""Scheduled action: stage 2 of two-stage RSS pipeline.

Acquires a pipeline lock, loads each RssFeed's XML (HTTP for feed_type='rss',
S3 for feed_type='scrape', written by `scrape_rss_sources`), parses with
feedparser, and writes new LinkEntity/LinkActivityEntity rows tagged with
source='rss'.
"""

import asyncio
import calendar
import os
import time
from typing import Optional

import feedparser
import httpx
from loguru import logger

from storage.repository import link as link_repo
from storage.service import link as link_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import rss_feed as rss_feed_service

from worker.link_downloader import s3_get


LOCK_NAME = "fetch_rss_links"

FAIL_THRESHOLD = int(os.environ.get("RSS_FAIL_THRESHOLD", 3))
FAIL_COOLDOWN = int(os.environ.get("RSS_FAIL_COOLDOWN_SECONDS", 86400))


def _in_cooldown(feed) -> bool:
    until = getattr(feed, "fetch_disabled_until", None)
    if until is None:
        return False
    return int(time.time() * 1000) < until


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


async def _load_feed_xml(client: httpx.AsyncClient, feed) -> Optional[bytes]:
    """For rss feeds fetch over HTTP; for scrape feeds read the staged XML from S3."""
    if (feed.feed_type or 'rss') == 'scrape':
        return await asyncio.to_thread(s3_get, f"rss/{feed.rss_feed_id}.xml")
    return await _fetch_xml(client, feed.url)


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
    if _in_cooldown(feed):
        return {"feed_id": feed.rss_feed_id, "added": 0, "skipped": "cooldown"}

    xml = await _load_feed_xml(client, feed)
    if xml is None:
        if (feed.feed_type or 'rss') == 'scrape':
            # No XML staged yet: stage 1 will record its own failure, don't double-count.
            return {"feed_id": feed.rss_feed_id, "added": 0, "skipped": "no staged xml"}
        rss_feed_service.record_fetch_failure(feed.rss_feed_id, FAIL_THRESHOLD, FAIL_COOLDOWN)
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": "fetch failed"}

    parsed = feedparser.parse(xml)
    if parsed.bozo and not parsed.entries:
        err = str(parsed.bozo_exception)
        logger.error("fetch_rss_links parse error feed={}: {}", feed.rss_feed_id, err)
        rss_feed_service.record_fetch_failure(feed.rss_feed_id, FAIL_THRESHOLD, FAIL_COOLDOWN)
        return {"feed_id": feed.rss_feed_id, "added": 0, "error": err}

    added, max_ts = _ingest_entries(user_id, feed, parsed)
    rss_feed_service.record_fetch_success(feed.rss_feed_id)
    if max_ts > (feed.last_item_ts or 0):
        rss_feed_service.update_fetch_state(feed.rss_feed_id, last_item_ts=max_ts)
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
                        try:
                            rss_feed_service.record_fetch_failure(
                                feed.rss_feed_id, FAIL_THRESHOLD, FAIL_COOLDOWN,
                            )
                        except Exception:
                            logger.exception("fetch_rss_links feed={} record_fetch_failure failed", feed.rss_feed_id)
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
