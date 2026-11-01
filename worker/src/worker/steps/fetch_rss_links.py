"""Scheduled action: stage 2 of two-stage RSS pipeline.

S3 -> feedparser -> link transform with best-effort URL alias resolution. For every RssFeed, read the staged
XML from s3://$Y_AGENT_S3_BUCKET/rss/<rss_feed_id>.xml, parse with feedparser,
and write new LinkEntity/LinkActivityEntity rows tagged with source='rss'.

Bounded HTTP redirect checks only for same-host, same-slug alias candidates. Missing or unparseable XML is
silently skipped — fetch failures are owned by stage 1 (`fetch_rss_xml`).
"""

import asyncio
import calendar
import os
import time
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx
from loguru import logger
from sqlalchemy.exc import IntegrityError

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


def _article_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), '', ''))


def _host_slug(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.netloc.lower(), parsed.path.rstrip('/').rsplit('/', 1)[-1]


def _normalized_title(title: Optional[str]) -> str:
    return ' '.join((title or '').split()).casefold()


def _is_rss_alias(candidate, url, title, published_at, resolved_old=None, resolved_new=None) -> bool:
    host, slug = _host_slug(url)
    if not host or not slug or _host_slug(candidate.base_url) != (host, slug):
        return False
    old, new = _article_url(candidate.base_url), _article_url(url)
    if old == new:
        return True
    if resolved_old and _article_url(resolved_old) == new:
        return True
    if resolved_new and _article_url(resolved_new) == old:
        return True
    return (
        published_at is not None and candidate.published_at == published_at
        and bool(_normalized_title(title))
        and _normalized_title(candidate.title) == _normalized_title(title)
    )


def _resolve_redirect(client, url: str) -> Optional[str]:
    try:
        response = client.head(url)
        response.raise_for_status()
        return str(response.url)
    except httpx.HTTPError:
        return None


def _find_alias(url, title, published_at, client) -> Optional[str]:
    candidates = link_service.find_rss_links_by_host_slug(url)
    # An exact row wins over any historical alias. The ordinary upsert owns it.
    if any(c.base_url == url.split('#', 1)[0].split('?', 1)[0] for c in candidates):
        return None
    for candidate in candidates:
        if _is_rss_alias(candidate, url, title, published_at):
            return candidate.link_id
    if client is not None and candidates:
        resolved_new = _resolve_redirect(client, url)
        for candidate in candidates:
            if _is_rss_alias(candidate, url, title, published_at,
                             resolved_old=_resolve_redirect(client, candidate.base_url),
                             resolved_new=resolved_new):
                return candidate.link_id
    return None


def _ingest_entries(user_id: int, feed, parsed, client=None) -> tuple[int, int]:
    """Insert new items into the link table. Returns (added, max_ts).

    Idempotent on (user_id, link_id): timestamp drift between refetches no longer
    produces duplicate activities. Every entry still upserts LinkEntity so that
    title / published_at / source get backfilled on existing rows.
    """
    last_item_ts = feed.last_item_ts or 0
    max_ts = last_item_ts
    added = 0

    # Feed-level fallback for dateless entries: <lastBuildDate>, else now.
    # Only used for the activity timestamp; published_at stays None and the
    # fallback is excluded from max_ts so it never advances last_item_ts.
    feed_ts_struct = parsed.feed.get("updated_parsed")
    fallback_ts = (
        int(calendar.timegm(feed_ts_struct) * 1000)
        if feed_ts_struct else int(time.time() * 1000)
    )

    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        ts_ms = _parse_feed_timestamp(entry)
        dated = ts_ms is not None
        timestamp = ts_ms if dated else fallback_ts
        published_at = ts_ms if dated else None

        title = entry.get("title")
        reuse_link_id = None
        try:
            reuse_link_id = _find_alias(url, title, published_at, client)
        except Exception:
            logger.exception("fetch_rss_links alias lookup failed feed={} url={}", feed.rss_feed_id, url)
        try:
            try:
                _, created = link_service.add_link_rss(
                    user_id, url, title=title, timestamp=timestamp,
                    published_at=published_at, source_feed_id=feed.rss_feed_id,
                    reuse_link_id=reuse_link_id,
                )
            except IntegrityError:
                # A concurrent feed may have inserted the target URL first.
                _, created = link_service.add_link_rss(
                    user_id, url, title=title, timestamp=timestamp,
                    published_at=published_at, source_feed_id=feed.rss_feed_id,
                )
            if created:
                added += 1
            if dated and ts_ms > max_ts:
                max_ts = ts_ms
        except Exception:
            logger.exception(
                "fetch_rss_links ingest failed feed={} url={}",
                feed.rss_feed_id, url,
            )
            continue

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

    with httpx.Client(timeout=5.0, follow_redirects=True, max_redirects=5) as client:
        added, max_ts = _ingest_entries(user_id, feed, parsed, client)
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
