"""Scheduled action: stage 1 of two-stage RSS pipeline.

For every RssFeed with feed_type='scrape', fetch the source HTML, apply the
configured CSS selectors via BeautifulSoup, render an RSS 2.0 XML document,
and upload it to s3://$Y_AGENT_S3_BUCKET/rss/<rss_feed_id>.xml. Stage 2
(`fetch_rss_links`) reads the XML back via feedparser to populate the link
table.

Failures are tracked separately from stage 2 via `scrape_failure_count` and
`scrape_last_run_at` so the two stages can fail (and cool down) independently.
"""

import asyncio
import os
import time
from email.utils import format_datetime
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from loguru import logger

from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import rss_feed as rss_feed_service

from worker.link_downloader import s3_put
from worker.steps._scrape_extract import extract_scrape_items, fetch_html


LOCK_NAME = "scrape_rss_sources"

FAIL_THRESHOLD = int(os.environ.get("RSS_SCRAPE_FAIL_THRESHOLD", 3))
FAIL_COOLDOWN = int(os.environ.get("RSS_SCRAPE_FAIL_COOLDOWN_SECONDS", 86400))


def _in_cooldown(feed) -> bool:
    if (feed.scrape_failure_count or 0) < FAIL_THRESHOLD:
        return False
    last = feed.scrape_last_run_at
    if not last:
        return False
    try:
        last_ms = int(datetime.fromisoformat(last).timestamp() * 1000)
    except ValueError:
        return False
    return int(time.time() * 1000) < last_ms + FAIL_COOLDOWN * 1000


def _xml_s3_key(rss_feed_id: str) -> str:
    return f"rss/{rss_feed_id}.xml"


def _build_rss_xml(feed, items: list[dict]) -> bytes:
    """Render a minimal RSS 2.0 XML document. ElementTree handles escaping."""
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = feed.title or feed.url
    ET.SubElement(channel, "link").text = feed.url
    ET.SubElement(channel, "description").text = ""
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc),
    )

    for it in items:
        url = it.get("url")
        if not url:
            continue
        item_el = ET.SubElement(channel, "item")
        title = it.get("title") or url
        ET.SubElement(item_el, "title").text = title
        ET.SubElement(item_el, "link").text = url
        ET.SubElement(item_el, "guid", {"isPermaLink": "true"}).text = url
        published_at = it.get("published_at")
        if published_at:
            dt = datetime.fromtimestamp(published_at / 1000, tz=timezone.utc)
            ET.SubElement(item_el, "pubDate").text = format_datetime(dt)

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


async def _process_feed(client: httpx.AsyncClient, user_id: int, feed) -> dict:
    if (feed.feed_type or 'rss') != 'scrape':
        return {"feed_id": feed.rss_feed_id, "skipped": "not scrape"}

    if _in_cooldown(feed):
        return {"feed_id": feed.rss_feed_id, "skipped": "cooldown"}

    if not feed.scrape_config or not feed.scrape_config.get('item_selector'):
        logger.error("scrape_rss_sources feed={} missing item_selector", feed.rss_feed_id)
        rss_feed_service.record_scrape_failure(feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "error": "missing item_selector"}

    html = await fetch_html(client, feed.url)
    if html is None:
        rss_feed_service.record_scrape_failure(feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "error": "fetch failed"}

    try:
        items = extract_scrape_items(feed, html)
    except Exception as e:
        logger.exception("scrape_rss_sources feed={} parse error", feed.rss_feed_id)
        rss_feed_service.record_scrape_failure(feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "error": f"parse error: {e}"}

    xml_bytes = _build_rss_xml(feed, items)
    try:
        s3_put(_xml_s3_key(feed.rss_feed_id), xml_bytes, content_type="application/rss+xml")
    except Exception as e:
        logger.exception("scrape_rss_sources feed={} s3 upload error", feed.rss_feed_id)
        rss_feed_service.record_scrape_failure(feed.rss_feed_id)
        return {"feed_id": feed.rss_feed_id, "error": f"s3 upload error: {e}"}

    rss_feed_service.record_scrape_success(feed.rss_feed_id)
    logger.info("scrape_rss_sources feed={} user={} items={}",
                feed.rss_feed_id, user_id, len(items))
    return {"feed_id": feed.rss_feed_id, "items": len(items)}


async def handle_scrape_rss_sources() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("scrape_rss_sources: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        all_feeds = rss_feed_service.list_all_feeds()
        scrape_feeds = [
            (uid, f) for uid, f in all_feeds if (f.feed_type or 'rss') == 'scrape'
        ]
        logger.info("scrape_rss_sources: scanning {} scrape feeds", len(scrape_feeds))
        if not scrape_feeds:
            return {"status": "ok", "action": LOCK_NAME, "feeds": 0}

        rate_limit = int(os.environ.get("RSS_SCRAPE_RATE_LIMIT", 10))
        semaphore = asyncio.Semaphore(rate_limit)
        timeout = int(os.environ.get("RSS_SCRAPE_TIMEOUT", 30))

        async with httpx.AsyncClient(timeout=timeout) as client:
            async def guarded(user_id, feed):
                async with semaphore:
                    try:
                        return await _process_feed(client, user_id, feed)
                    except Exception as e:
                        logger.exception("scrape_rss_sources feed={} unexpected error", feed.rss_feed_id)
                        try:
                            rss_feed_service.record_scrape_failure(feed.rss_feed_id)
                        except Exception:
                            logger.exception("scrape_rss_sources feed={} record_scrape_failure failed", feed.rss_feed_id)
                        return {"feed_id": feed.rss_feed_id, "error": str(e)}

            results = await asyncio.gather(
                *(guarded(user_id, feed) for user_id, feed in scrape_feeds)
            )

        errors = [r for r in results if r.get("error")]
        out = {"status": "ok", "action": LOCK_NAME, "feeds": len(scrape_feeds)}
        if errors:
            out["errors"] = errors
        return out
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
