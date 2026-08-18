"""xAI (Grok) search backend on the native Responses API.

Two backend values select the server-side search tool: `xai_web` (general web
search) and `xai_x` (X / Twitter search). Both are only reachable on xAI's own
`/v1/responses` endpoint; the `x-ai/*` models on OpenRouter do not expose these
tools.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import httpx

from storage.entity.dto import Message
from storage.util import generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp


DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4-1-fast"
REQUEST_TIMEOUT = 180.0

# Backend value -> server-side tool. The search mode lives in the backend value
# rather than in a new bot_config column, so `--backend xai_x` stays a usable
# filter and no migration is needed.
SEARCH_TOOLS = {
    "xai_web": "web_search",
    "xai_x": "x_search",
}


def resolve_base_url(base_url: Optional[str]) -> str:
    value = (base_url or "").strip().rstrip("/")
    return value or DEFAULT_BASE_URL


def resolve_model(model: Optional[str]) -> str:
    return (model or "").strip().strip('"').strip() or DEFAULT_MODEL


def resolve_tool(backend: Optional[str]) -> str:
    tool = SEARCH_TOOLS.get((backend or "").strip())
    if not tool:
        raise ValueError(f"Unknown xAI search backend: {backend!r}")
    return tool


def _to_input_items(messages: Iterable[dict]) -> List[Dict[str, Any]]:
    """Map chat-completions style messages onto Responses API input items.

    Assistant turns carry `output_text` parts, everything else `input_text`.
    """
    items = []
    for message in messages:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if not role or not content:
            continue
        part_type = "output_text" if role == "assistant" else "input_text"
        items.append({"role": role, "content": [{"type": part_type, "text": content}]})
    return items


def _extract_text_and_citations(response_data: dict) -> Tuple[str, List[Dict[str, Any]]]:
    """Collect assistant text + url_citation annotations from `output[]`.

    Never indexes `output[0]`: x_search reorders items (reasoning and tool-call
    items can precede or follow the message item). An `output` list with no
    message text is a legitimately empty result (the caller retries once); a
    response without a usable `output` list is malformed and raises, so a
    broken payload cannot become a blank successful answer.
    """
    if not isinstance(response_data, dict) or not isinstance(response_data.get("output"), list):
        raise ValueError(f"Malformed xAI response: {str(response_data)[:200]}")

    texts: List[str] = []
    citations: List[Dict[str, Any]] = []

    for item in response_data["output"]:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            for annotation in content.get("annotations") or []:
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                url = annotation.get("url")
                if not (isinstance(url, str) and url):
                    continue
                # Every valid annotation is kept, in response order: a repeated
                # URL is a second piece of attribution, not a duplicate row.
                entry: Dict[str, Any] = {"url": url}
                title = annotation.get("title")
                if isinstance(title, str) and title:
                    entry["title"] = title
                citations.append(entry)

    return "\n\n".join(texts), citations


def _assistant_message(content: str, model: str, links: Optional[List[Dict[str, Any]]] = None) -> Message:
    return Message(
        role="assistant",
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        id=generate_message_id(),
        provider="xai",
        model=model,
        links=links or None,
    )


async def run_xai_search(
    messages: Iterable[dict],
    bot_config,
    message_callback: Callable[[Message], None],
    chat_id: str = None,
    trace_id: str = None,
    topic: str = None,
) -> dict:
    """Call xAI /responses with a search tool and emit one assistant Message."""
    api_key = (bot_config.api_key or "").strip()
    if not api_key:
        raise ValueError("xAI search bot requires api_key")

    tool = resolve_tool(bot_config.backend or bot_config.api_type)
    base_url = resolve_base_url(bot_config.base_url)
    model = resolve_model(bot_config.model)
    payload = {
        "model": model,
        "input": _to_input_items(messages),
        "tools": [{"type": tool}],
        # Nothing here reads previous_response_id, so no server-side retention.
        "store": False,
    }
    if bot_config.max_tokens:
        payload["max_output_tokens"] = bot_config.max_tokens

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async def _search() -> dict:
            response = await client.post(f"{base_url}/responses", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

        response_data = await _search()
        content, links = _extract_text_and_citations(response_data)
        if not content:
            # x_search intermittently returns an empty window; one retry is
            # enough in practice, and a second empty result is returned as-is.
            response_data = await _search()
            content, links = _extract_text_and_citations(response_data)

    message_callback(_assistant_message(content, model, links=links))
    return {"status": "completed", "usage": response_data.get("usage") or {}}
