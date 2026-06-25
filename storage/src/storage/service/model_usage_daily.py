"""Provider-generic daily LLM usage: per-source pulls into one upsert table.

One source in scope:
- CRS (claude-relay-service): POST {origin}/apiStats/api/user-model-stats with each
  distinct cr_ relay key referenced by the user's bot_configs, period='daily' ->
  today's per-model tokens + real cost. The endpoint is strictly per-key, so we
  enumerate every distinct key and SUM per model to reconstruct the global per-model
  aggregate (cc1 is a single-user relay, so the sum equals CRS's own
  usage:model:daily:* global). Stored as scope='aggregate' rows (key enumeration is an
  invisible impl detail — no per-key rows). Today-only (no history); we pull daily.
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

def _crs_targets(user_id: int) -> list[tuple[str, str]]:
    """Distinct CRS (origin, api_key) pairs across the user's bot_configs.

    Enumerates every cr_ key referenced by a bot_config and dedups by
    (origin, api_key) so a key shared by multiple bots (e.g. the subscription key
    used by claude_code + codex) is queried once. Self-maintaining: a new bot
    repointed to CRS is auto-discovered with no code change here. Enumeration is an
    invisible impl detail — the results are summed into one global aggregate."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for c in bot_config_service.list_configs(user_id):
        ak = c.api_key or ""
        if not ak.startswith("cr_"):
            continue
        parts = urlsplit(c.base_url or "https://cc1.yovy.app/api")
        origin = f"{parts.scheme or 'https'}://{parts.netloc}"
        target = (origin, ak)
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _fetch_crs_key(origin: str, api_key: str) -> list[dict]:
    """Today's per-model items for one CRS key (raises on transport/HTTP error)."""
    resp = httpx.post(
        f"{origin}/apiStats/api/user-model-stats",
        json={"apiKey": api_key, "period": "daily"},
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data") or []


def sync_crs(user_id: int, synced_at: str | None = None) -> dict:
    """Pull today's per-model usage across all distinct CRS keys, SUM per model, and
    upsert as global source='crs' scope='aggregate' rows (one row per model)."""
    targets = _crs_targets(user_id)
    if not targets:
        return {"source": "crs", "status": "skip", "reason": "no cr_ keys in bot_configs", "rows": 0}

    # model -> summed totals across every distinct key (the global per-model aggregate).
    agg: dict[str, dict] = {}
    for origin, api_key in targets:
        try:
            items = _fetch_crs_key(origin, api_key)
        except Exception as e:
            logger.exception("sync_crs: fetch failed for a key: {}", e)
            return {"source": "crs", "status": "error", "reason": str(e), "rows": 0}
        for item in items:
            model = item.get("model") or "*"
            costs = item.get("costs") or {}
            row = agg.setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cache_create_tokens": 0,
                "cache_read_tokens": 0, "all_tokens": 0, "requests": 0, "cost": 0.0,
            })
            row["input_tokens"] += item.get("inputTokens") or 0
            row["output_tokens"] += item.get("outputTokens") or 0
            row["cache_create_tokens"] += item.get("cacheCreateTokens") or 0
            row["cache_read_tokens"] += item.get("cacheReadTokens") or 0
            row["all_tokens"] += item.get("allTokens") or 0
            row["requests"] += item.get("requests") or 0
            row["cost"] += costs.get("real", costs.get("total", 0.0)) or 0.0

    usage_date = _local_today()
    rows = [{
        "usage_date": usage_date,
        "source": "crs",
        "provider": _derive_provider(model),
        "model": model,
        "scope": "aggregate",
        "scope_id": "",
        "scope_name": "",
        "cost_basis": "real",
        **totals,
    } for model, totals in agg.items()]

    n = upsert_daily(user_id, rows, synced_at)
    logger.info("sync_crs: {} keys -> upserted {} aggregate rows for {}", len(targets), n, usage_date)
    return {"source": "crs", "status": "ok", "rows": n, "date": usage_date}


# --- orchestration ----------------------------------------------------------

def sync(user_id: int, source: str | None = None) -> dict:
    """Run the enabled source pulls. `source` filters to one of crs."""
    synced_at = get_utc_iso8601_timestamp()
    results = []
    if source in (None, "crs"):
        results.append(sync_crs(user_id, synced_at))
    return {"status": "ok", "results": results}
