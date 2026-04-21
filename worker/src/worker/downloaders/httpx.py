"""HTTPX downloader — direct HTTP GET + readability + markdownify.

Lightweight, no external scraper. Returns markdown in `content`.
"""

import httpx
from loguru import logger


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _html_to_markdown(html: str) -> tuple[str, str]:
    """Extract title and markdown content from raw HTML via readability + markdownify."""
    from readability import Document
    from markdownify import markdownify as md_convert

    doc = Document(html)
    title = (doc.short_title() or doc.title() or "").strip()
    summary_html = doc.summary(html_partial=True)
    markdown = md_convert(summary_html, heading_style="ATX").strip()
    return title, markdown


async def download(url: str, timeout: int = 30) -> dict:
    """Fetch `url` via httpx and convert to markdown."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_UA, "Accept": "text/html,*/*;q=0.8"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {
                "status": "failed",
                "title": None,
                "content": None,
                "method_used": "httpx",
                "error": f"HTTP {resp.status_code}",
            }

        title, markdown = _html_to_markdown(resp.text)
        if not markdown.strip():
            return {
                "status": "failed",
                "title": title or None,
                "content": None,
                "method_used": "httpx",
                "error": "Empty content after extraction",
            }
        return {
            "status": "done",
            "title": title or None,
            "content": markdown,
            "method_used": "httpx",
            "error": None,
        }
    except Exception as e:
        logger.warning("httpx download failed for {}: {}", url, e)
        return {
            "status": "failed",
            "title": None,
            "content": None,
            "method_used": "httpx",
            "error": str(e),
        }
