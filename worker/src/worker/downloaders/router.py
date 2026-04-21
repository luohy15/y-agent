"""Route a URL to the appropriate downloader.

Routing rules:
- mp.weixin.qq.com / twitter.com / x.com / youtube.com / youtu.be / bilibili.com → ssh (opencli)
- everything else → httpx; fallback to oxylabs on failure
"""

from urllib.parse import urlparse

from loguru import logger

from worker.downloaders import httpx as httpx_dl
from worker.downloaders import oxylabs as oxylabs_dl
from worker.downloaders import ssh as ssh_dl


SSH_DOMAINS = (
    "mp.weixin.qq.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "bilibili.com",
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _needs_ssh(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    for d in SSH_DOMAINS:
        if host == d or host.endswith("." + d):
            return True
    return False


async def route_and_download(
    user_id: int,
    url: str,
    timeout: int = 300,
) -> dict:
    """Dispatch to ssh / httpx / oxylabs based on domain.

    Returns `{status, title, content, method_used, error}`. All downloaders
    return markdown content in memory; the caller is responsible for persisting it.
    """
    if _needs_ssh(url):
        return await ssh_dl.download(user_id, url, timeout=timeout)

    primary = await httpx_dl.download(url, timeout=min(timeout, 30))
    if primary["status"] == "done":
        return primary

    logger.info(
        "httpx failed for {} ({}), falling back to oxylabs",
        url,
        primary.get("error"),
    )
    fallback = await oxylabs_dl.download(url, timeout=min(timeout, 120))
    if fallback["status"] == "done":
        return fallback
    # Return the oxylabs failure (more informative than httpx for blocked sites),
    # but preserve the httpx error hint in the message.
    fallback["error"] = (
        f"httpx: {primary.get('error')} | oxylabs: {fallback.get('error')}"
    )
    return fallback
