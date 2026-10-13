"""Scheduled action: download a batch of pending links (link- or activity-level).

Mirrors alpha_vantage_news's step2_content_crawler: acquires a pipeline lock,
queries unprocessed links, downloads them with bounded concurrency via the
router, increments crawl_fail_count on failure, and self-invokes if there is
still more work to do.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from loguru import logger

from storage.repository import link as link_repo
from storage.service import link as link_service
from storage.service import pipeline_lock as pipeline_lock_service

from worker.downloaders.router import route_and_download
from worker.downloaders.ssh import write_markdown
from worker.link_downloader import s3_get
from worker.steps._feed_body import feed_markdown, index_feed_entries, select_feed_body


LOCK_NAME = "batch_download_links"
DEFAULT_BATCH_SIZE = 50
DEFAULT_RATE_LIMIT = 10
DEFAULT_MAX_FAILS = 5
DEFAULT_DOWNLOAD_TIMEOUT = 120


def _markdown_from_feed(item: dict, feed_indexes: dict | None) -> str | None:
    """Return feed markdown for a link-level RSS item, or None to page-fetch."""
    if item.get("activity_id") or not feed_indexes:
        return None
    feed_id = item.get("source_feed_id")
    if not feed_id:
        return None
    entry = feed_indexes.get(feed_id, {}).get(item.get("base_url") or "")
    if entry is None:
        return None
    html = select_feed_body(entry)
    if not html:
        return None
    title = entry.get("title") or item.get("url")
    return feed_markdown(title, item["url"], html)


async def _index_feed(feed_id: str) -> dict:
    """Index one staged feed. Missing or bad XML is an empty index (page fetch)."""
    try:
        xml = await asyncio.to_thread(s3_get, f"rss/{feed_id}.xml")
    except Exception as e:
        logger.warning("batch_download_links feed xml read failed feed={}: {}", feed_id, e)
        return {}
    if not xml:
        return {}
    try:
        return index_feed_entries(xml)
    except Exception as e:
        logger.warning("batch_download_links feed xml index failed feed={}: {}", feed_id, e)
        return {}


async def _load_feed_indexes(pending: list[dict]) -> dict:
    feed_ids: list[str] = []
    seen: set[str] = set()
    for item in pending:
        if item.get("activity_id"):
            continue
        feed_id = item.get("source_feed_id")
        if feed_id and feed_id not in seen:
            seen.add(feed_id)
            feed_ids.append(feed_id)
    if not feed_ids:
        return {}
    pairs = await asyncio.gather(*(_index_feed(feed_id) for feed_id in feed_ids))
    return dict(zip(feed_ids, pairs))


async def _download_one(item: dict, timeout: int, feed_indexes: dict | None = None) -> str:
    """Download a single link/activity, write content, update status.

    `item` keys: user_id, link_id, base_url, url, activity_id (optional),
    source_feed_id (link-level only). Returns 'success' or 'error'.
    A usable feed body is written as-is; failure counts as a normal download
    failure and does not fall through to a page fetch in the same attempt.
    """
    user_id = item["user_id"]
    link_id = item["link_id"]
    url = item["url"]
    activity_id = item.get("activity_id")
    link_service.update_download_status(link_id, "downloading", url=url)

    try:
        markdown = _markdown_from_feed(item, feed_indexes)
        if markdown is not None:
            result = await write_markdown(user_id, url, markdown, link_id, timeout=timeout)
        else:
            result = await route_and_download(user_id, url, timeout=timeout, link_id=link_id, activity_id=activity_id)
    except Exception as e:
        logger.exception("batch_download_links download crashed for link={} url={}: {}", link_id, url, e)
        link_repo.increment_crawl_fail_count(link_id)
        link_service.update_download_status(link_id, "failed", url=url)
        return "error"

    method = result.get("method_used")
    if result.get("status") != "done":
        logger.warning(
            "batch_download_links failed link={} url={} method={}: {}",
            link_id, url, method, result.get("error"),
        )
        link_repo.increment_crawl_fail_count(link_id)
        link_service.update_download_status(link_id, "failed", url=url)
        return "error"

    try:
        logger.info(
            "batch_download_links ok link={} url={} method={} path={} title={!r}",
            link_id, url, method, result.get("path"), (result.get("title") or "")[:80],
        )
        return "success"
    except Exception as e:
        logger.exception("batch_download_links persist crashed for link={}: {}", link_id, e)
        link_repo.increment_crawl_fail_count(link_id)
        link_service.update_download_status(link_id, "failed", url=url)
        return "error"


def _self_invoke() -> bool:
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    if not function_name:
        return False
    try:
        import importlib
        boto = importlib.import_module("boto" + "3")
        client = boto.client("lambda")
        client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps({"action": LOCK_NAME}),
        )
        logger.info("batch_download_links self-invoked for continuation")
        return True
    except Exception as e:
        logger.warning("batch_download_links self-invoke failed: {}", e)
        return False


async def handle_batch_download_links() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("batch_download_links: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    batch_size = int(os.environ.get("BATCH_DOWNLOAD_SIZE", DEFAULT_BATCH_SIZE))
    rate_limit = int(os.environ.get("CRAWLER_RATE_LIMIT", DEFAULT_RATE_LIMIT))
    max_fails = int(os.environ.get("BATCH_DOWNLOAD_MAX_FAILS", DEFAULT_MAX_FAILS))
    timeout = int(os.environ.get("CRAWLER_TIMEOUT", DEFAULT_DOWNLOAD_TIMEOUT))

    try:
        pending = link_repo.list_pending_downloads(batch_size, max_fails=max_fails)
        logger.info(
            "batch_download_links: picked {} (batch={}, max_fails={}, rate_limit={})",
            len(pending), batch_size, max_fails, rate_limit,
        )
        if not pending:
            return {
                "status": "ok",
                "action": LOCK_NAME,
                "picked": 0,
                "success": 0,
                "error": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        feed_indexes = await _load_feed_indexes(pending)
        semaphore = asyncio.Semaphore(rate_limit)

        async def guarded(item):
            async with semaphore:
                return await _download_one(item, timeout=timeout, feed_indexes=feed_indexes)

        results = await asyncio.gather(*(guarded(item) for item in pending))
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)

    success = sum(1 for r in results if r == "success")
    error = len(results) - success
    logger.info("batch_download_links: success={} error={}", success, error)

    continued = False
    if len(pending) >= batch_size:
        continued = _self_invoke()

    return {
        "status": "ok",
        "action": LOCK_NAME,
        "picked": len(pending),
        "success": success,
        "error": error,
        "continued": continued,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
