"""Scheduled action: stage 2 of two-stage RSS pipeline.

Pure S3 -> feedparser -> link transform. For every RssFeed, read the staged
XML from s3://$Y_AGENT_S3_BUCKET/rss/<rss_feed_id>.xml, parse with feedparser,
and write new LinkEntity/LinkActivityEntity rows tagged with source='rss'.

No HTTP IO, no cooldown, no failure tracking. Missing or unparseable XML is
silently skipped — fetch failures are owned by stage 1 (`fetch_rss_xml`).
"""

import asyncio
import calendar
import os
from typing import Optional

import feedparser
from loguru import logger

from storage.service import link as link_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import rss_feed as rss_feed_service

from worker.link_downloader import s3_get


LOCK_NAME = "fetch_rss_links"


def _parse_feed_timestamp(entry) -> Optional[int]:
    ts_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not ts_struct:
        return None
    return int(calendar.timegm(ts_struct) * 1000)


def _ingest_entries(user_id: int, feed, parsed) -> tuple[int, int]:
    """Insert new items into the link table. Returns (added, max_ts).

    Idempotent on (user_id, link_id): timestamp drift between refetches no longer
    produces duplicate activities. Every entry still upserts LinkEntity so that
    title / published_at / source get backfilled on existing rows.
    """
    last_item_ts = feed.last_item_ts or 0
    max_ts = last_item_ts
    added = 0

    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        ts_ms = _parse_feed_timestamp(entry)
        if ts_ms is None:
            continue

        title = entry.get("title")
        if ts_ms > last_item_ts:
            _, created = link_service.add_link_rss(
                user_id, url, title=title, timestamp=ts_ms,
                published_at=ts_ms, source_feed_id=feed.rss_feed_id,
            )
            if created:
                added += 1
            if ts_ms > max_ts:
                max_ts = ts_ms
        else:
            link_service.upsert_link_info(
                url, title=title, published_at=ts_ms,
                source="rss", source_feed_id=feed.rss_feed_id,
            )

    return added, max_ts


def _process_feed(user_id: int, feed) -> dict:
    xml = s3_get(f"rss/{feed.rss_feed_id}.xml")
    if xml is None:
        return {"feed_id": feed.rss_feed_id, "added": 0, "skipped": "no_xml"}

    parsed = feedparser.parse(xml)
    if parsed.bozo and not parsed.entries:
        logger.warning("fetch_rss_links parse warn feed={}: {}",
                       feed.rss_feed_id, parsed.bozo_exception)
        return {"feed_id": feed.rss_feed_id, "added": 0, "skipped": "bad_xml"}

    added, max_ts = _ingest_entries(user_id, feed, parsed)
    if max_ts > (feed.last_item_ts or 0):
        rss_feed_service.update_last_item_ts(feed.rss_feed_id, max_ts)
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

        rate_limit = int(os.environ.get("RSS_INGEST_RATE_LIMIT", 32))
        semaphore = asyncio.Semaphore(rate_limit)

        async def guarded(user_id, feed):
            async with semaphore:
                try:
                    return await asyncio.to_thread(_process_feed, user_id, feed)
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
