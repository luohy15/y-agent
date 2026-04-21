"""Oxylabs Web Scraper API downloader.

POSTs to realtime.oxylabs.io/v1/queries with Basic auth, extracts HTML, then runs
readability + markdownify locally. Credentials come from env `OXYLABS_USERNAME` /
`OXYLABS_PASSWORD`.
"""

import os

import httpx
from loguru import logger

from worker.downloaders.httpx import _html_to_markdown


OXYLABS_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"


async def download(url: str, timeout: int = 120) -> dict:
    """Fetch `url` via Oxylabs Web Scraper API and convert to markdown."""
    username = os.environ.get("OXYLABS_USERNAME")
    password = os.environ.get("OXYLABS_PASSWORD")
    if not username or not password:
        return {
            "status": "failed",
            "title": None,
            "content": None,
            "method_used": "oxylabs",
            "error": "OXYLABS_USERNAME / OXYLABS_PASSWORD not set",
        }

    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                OXYLABS_ENDPOINT,
                json=payload,
                auth=(username, password),
            )
        if resp.status_code >= 400:
            return {
                "status": "failed",
                "title": None,
                "content": None,
                "method_used": "oxylabs",
                "error": f"oxylabs HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        results = data.get("results") or []
        if not results:
            return {
                "status": "failed",
                "title": None,
                "content": None,
                "method_used": "oxylabs",
                "error": "oxylabs returned no results",
            }
        first = results[0]
        inner_status = first.get("status_code")
        html = first.get("content") or ""
        if inner_status and inner_status >= 400:
            return {
                "status": "failed",
                "title": None,
                "content": None,
                "method_used": "oxylabs",
                "error": f"oxylabs target HTTP {inner_status}",
            }
        if not html:
            return {
                "status": "failed",
                "title": None,
                "content": None,
                "method_used": "oxylabs",
                "error": "oxylabs returned empty content",
            }

        title, markdown = _html_to_markdown(html)
        if not markdown.strip():
            return {
                "status": "failed",
                "title": title or None,
                "content": None,
                "method_used": "oxylabs",
                "error": "Empty content after extraction",
            }
        return {
            "status": "done",
            "title": title or None,
            "content": markdown,
            "method_used": "oxylabs",
            "error": None,
        }
    except Exception as e:
        logger.warning("oxylabs download failed for {}: {}", url, e)
        return {
            "status": "failed",
            "title": None,
            "content": None,
            "method_used": "oxylabs",
            "error": str(e),
        }
