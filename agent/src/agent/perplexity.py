"""Perplexity chat-completions backend."""

from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

from storage.entity.dto import Message
from storage.util import generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp


DEFAULT_BASE_URL = "https://api.perplexity.ai"
DEFAULT_MODEL = "sonar"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_base_url(base_url: Optional[str]) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value or value == OPENROUTER_BASE_URL:
        return DEFAULT_BASE_URL
    return value


def resolve_model(model: Optional[str]) -> str:
    return (model or "").strip().strip('"').strip() or DEFAULT_MODEL


_SEARCH_RESULT_FIELDS = ("title", "snippet", "last_updated")


def _extract_citations(response_data: dict) -> List[Dict[str, Any]]:
    meta_by_url: Dict[str, Dict[str, Any]] = {}
    for result in response_data.get("search_results") or []:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not (isinstance(url, str) and url):
            continue
        meta = meta_by_url.setdefault(url, {})
        for field in _SEARCH_RESULT_FIELDS:
            value = result.get(field)
            if isinstance(value, str) and value and field not in meta:
                meta[field] = value

    citations: List[Dict[str, Any]] = []
    seen = set()

    def _add(url: str) -> None:
        if url in seen:
            return
        seen.add(url)
        entry: Dict[str, Any] = {"url": url}
        entry.update(meta_by_url.get(url, {}))
        citations.append(entry)

    for url in response_data.get("citations") or []:
        if isinstance(url, str) and url:
            _add(url)

    for url in meta_by_url:
        _add(url)

    return citations


def _assistant_message(content: str, model: str, links: Optional[List[Dict[str, Any]]] = None) -> Message:
    return Message(
        role="assistant",
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        id=generate_message_id(),
        provider="perplexity",
        model=model,
        links=links or None,
    )


async def run_perplexity(
    messages: Iterable[dict],
    bot_config,
    message_callback: Callable[[Message], None],
    chat_id: str = None,
    trace_id: str = None,
    topic: str = None,
) -> dict:
    """Call Perplexity /chat/completions and emit one assistant Message."""
    api_key = (bot_config.api_key or "").strip()
    if not api_key:
        raise ValueError("Perplexity bot requires api_key")

    base_url = resolve_base_url(bot_config.base_url)
    model = resolve_model(bot_config.model)
    payload = {
        "model": model,
        "messages": list(messages),
        "stream": False,
    }
    if bot_config.max_tokens:
        payload["max_tokens"] = bot_config.max_tokens

    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()

    content = (((response_data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    links = _extract_citations(response_data)

    message_callback(_assistant_message(content, model, links=links))
    return {"status": "completed", "usage": response_data.get("usage") or {}}
