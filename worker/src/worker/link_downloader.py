"""Download link content via the downloaders router (ssh / httpx / oxylabs)."""

from loguru import logger

from storage.service import link as link_service
from worker.downloaders import ssh as ssh_dl
from worker.downloaders.router import route_and_download


def _content_path(link_id: str, activity_id: str = None) -> str:
    """Generate relative content path. Use activity_id for activity-level content."""
    if activity_id:
        return f"links/{link_id}/{activity_id}/content.md"
    return f"links/{link_id}/content.md"


async def run_link_download(user_id: int, link_id: str, url: str, activity_id: str = None):
    """Download link content via the router and persist result to storage."""
    url = url.split('#')[0]  # strip fragment
    link_service.update_download_status(link_id, "downloading", url=url)

    try:
        content_key = _content_path(link_id, activity_id)
        result = await route_and_download(user_id, url, content_key, timeout=300)
        method = result.get("method_used")
        logger.info(
            "download result for {}: status={} method={} title={!r}",
            url, result.get("status"), method, (result.get("title") or "")[:80],
        )

        if result.get("status") != "done":
            logger.warning("download failed for {}: {}", url, result.get("error"))
            link_service.update_download_status(link_id, "failed", url=url)
            return

        content = result.get("content")
        if content is not None:
            # httpx / oxylabs produced content in memory — write to shared filesystem.
            await ssh_dl.save_content_remote(user_id, content_key, content)

        link_service.update_download_status(
            link_id, "done", content_key=content_key, url=url
        )
        if result.get("title"):
            link_service.update_link_title(link_id, result["title"])

    except Exception as e:
        logger.exception("Link download failed: {}", e)
        link_service.update_download_status(link_id, "failed", url=url)
        raise
