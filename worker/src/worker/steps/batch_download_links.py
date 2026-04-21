"""Scheduled action: download a batch of pending RSS-sourced links.

Mirrors alpha_vantage_news's step2_content_crawler: acquires a pipeline lock,
queries unprocessed links, downloads them with bounded concurrency via the
router, increments crawl_fail_count on failure, and self-invokes if there is
still more work to do.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import boto3
from loguru import logger

from storage.repository import link as link_repo
from storage.service import link as link_service
from storage.service import pipeline_lock as pipeline_lock_service

from worker.downloaders import ssh as ssh_dl
from worker.downloaders.router import route_and_download


LOCK_NAME = "batch_download_links"
DEFAULT_BATCH_SIZE = 50
DEFAULT_RATE_LIMIT = 10
DEFAULT_MAX_FAILS = 5
DEFAULT_DOWNLOAD_TIMEOUT = 120


def _content_path(link_id: str) -> str:
    return f"links/{link_id}/content.md"


async def _download_one(user_id: int, link_id: str, base_url: str, timeout: int) -> str:
    """Download a single link, write content, update status. Returns 'success' or 'error'."""
    url = base_url
    content_key = _content_path(link_id)
    link_service.update_download_status(link_id, "downloading", url=url)

    try:
        result = await route_and_download(user_id, url, content_key, timeout=timeout)
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

    content = result.get("content")
    try:
        if content is not None:
            await ssh_dl.save_content_remote(user_id, content_key, content)
        link_service.update_download_status(link_id, "done", content_key=content_key, url=url)
        if result.get("title"):
            link_service.update_link_title(link_id, result["title"])
        logger.info(
            "batch_download_links ok link={} url={} method={} title={!r}",
            link_id, url, method, (result.get("title") or "")[:80],
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
        client = boto3.client("lambda")
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
        pending = link_repo.list_pending_rss_links(batch_size, max_fails=max_fails)
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

        semaphore = asyncio.Semaphore(rate_limit)

        async def guarded(item):
            async with semaphore:
                return await _download_one(
                    user_id=item["user_id"],
                    link_id=item["link_id"],
                    base_url=item["base_url"],
                    timeout=timeout,
                )

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
