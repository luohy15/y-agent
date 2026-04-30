"""Oxylabs Web Scraper API helpers + Chrome cookie loader."""

import json
import os
from typing import Any, Optional

import httpx
from loguru import logger


def load_cookies_from_chrome(domain: str) -> list[dict]:
    """Load cookies from Chrome browser for a specific domain.

    Returns cookies in Oxylabs format: [{'key': name, 'value': val}].
    """
    import browser_cookie3

    cj = browser_cookie3.chrome(domain_name=domain)
    cookies = [
        {'key': cookie.name, 'value': cookie.value}
        for cookie in cj
        if cookie.name and cookie.value
    ]
    logger.info(f"Loaded {len(cookies)} cookies from Chrome for {domain}")
    return cookies


async def fetch_raw(
    client: httpx.AsyncClient,
    url: str,
    cookies: Optional[list[dict]] = None,
    timeout: int = 30,
) -> str:
    """Fetch raw content from a URL via Oxylabs."""
    username = os.environ.get('OXYLABS_USERNAME')
    password = os.environ.get('OXYLABS_PASSWORD')

    if not username or not password:
        raise Exception("Oxylabs credentials not configured")

    payload: dict[str, Any] = {'source': 'universal', 'url': url}
    if cookies:
        payload['context'] = [
            {'key': 'force_cookies', 'value': True},
            {'key': 'cookies', 'value': cookies},
        ]

    resp = await client.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(username, password),
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get('results') or []
    if not results:
        raise Exception(f"No results from Oxylabs for {url}")

    content = results[0].get('content')
    if not content:
        raise Exception(f"No content in Oxylabs response for {url}")

    return content


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    cookies: Optional[list[dict]] = None,
    timeout: int = 30,
) -> dict:
    """Fetch and parse JSON from a URL via Oxylabs."""
    return json.loads(await fetch_raw(client, url, cookies, timeout))
