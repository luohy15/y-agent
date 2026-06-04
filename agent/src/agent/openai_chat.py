"""OpenAI-compatible chat-completions backend."""

from typing import Callable, Iterable, Optional

import httpx

from storage.entity.dto import Message, effective_openrouter_config
from storage.util import generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def resolve_base_url(base_url: Optional[str]) -> str:
    value = (base_url or "").strip().rstrip("/")
    return value or DEFAULT_BASE_URL


def resolve_model(model: Optional[str]) -> str:
    return (model or "").strip().strip('"').strip() or DEFAULT_MODEL


def _api_path(bot_config) -> str:
    return (getattr(bot_config, "custom_api_path", None) or "/chat/completions").lstrip("/")


def _provider_payload(bot_config):
    config = effective_openrouter_config(bot_config)
    if not config:
        return None
    return config.get("provider", config)


def _assistant_message(content: str, model: str) -> Message:
    return Message(
        role="assistant",
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        id=generate_message_id(),
        provider="openai",
        model=model,
    )


async def openai_chat_completion(
    messages: list[dict],
    bot_config,
    *,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    extra_payload: dict | None = None,
    timeout: float = 120.0,
) -> tuple[str, dict]:
    """Call an OpenAI-compatible /chat/completions endpoint."""
    api_key = (bot_config.api_key or "").strip()
    if not api_key:
        raise ValueError("OpenAI bot requires api_key")

    model = resolve_model(bot_config.model)
    outbound_messages = list(messages)
    if system_prompt and (not outbound_messages or outbound_messages[0].get("role") != "system"):
        outbound_messages.insert(0, {"role": "system", "content": system_prompt})

    payload = {
        "model": model,
        "messages": outbound_messages,
        "stream": False,
    }
    token_limit = max_tokens if max_tokens is not None else getattr(bot_config, "max_tokens", None)
    if token_limit:
        payload["max_tokens"] = token_limit
    provider = _provider_payload(bot_config)
    if provider:
        payload["provider"] = provider
    if extra_payload:
        payload.update(extra_payload)

    base_url = resolve_base_url(bot_config.base_url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/{_api_path(bot_config)}", json=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected LLM response: {response_data}") from exc
    return content, response_data


async def run_openai(
    messages: Iterable[dict],
    bot_config,
    message_callback: Callable[[Message], None],
    chat_id: str = None,
    trace_id: str = None,
    topic: str = None,
) -> dict:
    """Call OpenAI-compatible chat completions and emit one assistant Message."""
    content, response_data = await openai_chat_completion(list(messages), bot_config)
    message_callback(_assistant_message(content, resolve_model(bot_config.model)))
    return {"status": "completed", "usage": response_data.get("usage") or {}}
