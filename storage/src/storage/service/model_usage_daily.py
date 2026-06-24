"""Provider-generic daily LLM usage: per-source pulls into one upsert table.

One source in scope:
- CRS (claude-relay-service): POST {origin}/apiStats/api/user-model-stats with the
  cr_ relay key (from bot_config 'claude_code'), period='daily' -> today's per-model
  tokens + real cost. Today-only (no history in the response); we pull daily. The
  generic per-model capture covers any vendor routed through CRS (incl. OpenRouter).
"""

import os
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from storage.repository import model_usage_daily as repo
from storage.service import bot_config as bot_config_service
from storage.util import get_utc_iso8601_timestamp

# Cloudflare in front of CRS blocks the default urllib/httpx UA (error 1010).
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


# --- thin storage passthroughs ---------------------------------------------

def upsert_daily(user_id: int, rows: list[dict], synced_at: str | None = None) -> int:
    return repo.upsert_daily(user_id, rows, synced_at or get_utc_iso8601_timestamp())


def list_for(user_id: int, source: str | None = None, from_date: str | None = None, to_date: str | None = None, limit: int = 1000):
    return repo.list_for(user_id, source=source, from_date=from_date, to_date=to_date, limit=limit)


# --- helpers ----------------------------------------------------------------

def _derive_provider(model: str) -> str:
    """Map a model id to its vendor. OpenRouter ids are 'vendor/model'; CRS ids
    are bare (e.g. 'claude-opus-4-8', 'gpt-5.5')."""
    if not model or model == "*":
        return ""
    if "/" in model:
        return model.split("/", 1)[0]
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    if m.startswith("grok"):
        return "x-ai"
    if m.startswith("glm"):
        return "z-ai"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("qwen"):
        return "qwen"
    if m.startswith(("kimi", "moonshot")):
        return "moonshotai"
    if m.startswith("minimax"):
        return "minimax"
    return ""


def _local_today() -> str:
    """Today's date in the configured timezone (CRS stamps daily keys in its app
    TZ; we mirror Y_AGENT_TIMEZONE, defaulting to Asia/Shanghai = UTC+8)."""
    tz_name = os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    return datetime.now(tz).date().isoformat()


# --- CRS pull ---------------------------------------------------------------

def sync_crs(user_id: int, synced_at: str | None = None) -> dict:
    """Pull today's per-model usage from CRS and upsert as source='crs' rows."""
    config = bot_config_service.get_config(user_id, name="claude_code")
    if not config or not config.api_key:
        return {"source": "crs", "status": "skip", "reason": "no claude_code bot api_key", "rows": 0}

    parts = urlsplit(config.base_url or "https://cc1.yovy.app/api")
    origin = f"{parts.scheme or 'https'}://{parts.netloc}"
    url = f"{origin}/apiStats/api/user-model-stats"

    try:
        resp = httpx.post(
            url,
            json={"apiKey": config.api_key, "period": "daily"},
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.exception("sync_crs: fetch failed: {}", e)
        return {"source": "crs", "status": "error", "reason": str(e), "rows": 0}

    usage_date = _local_today()
    rows: list[dict] = []
    for item in payload.get("data") or []:
        model = item.get("model") or "*"
        costs = item.get("costs") or {}
        rows.append({
            "usage_date": usage_date,
            "source": "crs",
            "provider": _derive_provider(model),
            "model": model,
            "scope": "aggregate",
            "scope_id": "",
            "scope_name": "",
            "input_tokens": item.get("inputTokens") or 0,
            "output_tokens": item.get("outputTokens") or 0,
            "cache_create_tokens": item.get("cacheCreateTokens") or 0,
            "cache_read_tokens": item.get("cacheReadTokens") or 0,
            "all_tokens": item.get("allTokens") or 0,
            "requests": item.get("requests") or 0,
            "cost": costs.get("real", costs.get("total", 0.0)) or 0.0,
            "cost_basis": "real",
        })

    n = upsert_daily(user_id, rows, synced_at)
    logger.info("sync_crs: upserted {} rows for {}", n, usage_date)
    return {"source": "crs", "status": "ok", "rows": n, "date": usage_date}


# --- orchestration ----------------------------------------------------------

def sync(user_id: int, source: str | None = None) -> dict:
    """Run the enabled source pulls. `source` filters to one of crs."""
    synced_at = get_utc_iso8601_timestamp()
    results = []
    if source in (None, "crs"):
        results.append(sync_crs(user_id, synced_at))
    return {"status": "ok", "results": results}
