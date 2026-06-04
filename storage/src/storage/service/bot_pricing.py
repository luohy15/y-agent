"""Best-effort OpenRouter price lookup shared by `y bot list` / `y bot get` and
the `/api/bot/list` controller.

Prices come from the public OpenRouter model catalog (no auth). Fetch the catalog
via `fetch_openrouter_catalog()` (module-level TTL cache so the list request path
doesn't hit openrouter.ai on every call), then resolve each bot with
`bot_prices_per_1m()`."""

import time

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Module-level TTL cache for the catalog fetch. The catalog rarely changes and a
# stale entry only affects displayed prices, so a coarse TTL is fine and keeps the
# sidebar / list request path from hitting openrouter.ai on every refresh.
_CATALOG_TTL_SECONDS = 600  # 10 minutes
_catalog_cache = None
_catalog_cached_at = 0.0


def is_openrouter(bot_cfg) -> bool:
    """A bot routes through OpenRouter if its base_url targets the OpenRouter API
    (directly or via the Cloudflare AI gateway '.../openrouter' endpoint)."""
    return "openrouter" in (bot_cfg.base_url or "").lower()


def _fetch_openrouter_catalog_uncached():
    """Fetch the public OpenRouter model catalog. Best-effort: returns a
    {model_id: model} dict, or None if the request fails (offline / non-200)."""
    try:
        resp = httpx.get(OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        return {m["id"]: m for m in resp.json()["data"]}
    except Exception:
        return None


def fetch_openrouter_catalog():
    """Return the OpenRouter model catalog, cached at module level for
    `_CATALOG_TTL_SECONDS`. A failed fetch (None) is not cached, so the next call
    retries. Single-shot CLI processes are unaffected by the cache."""
    global _catalog_cache, _catalog_cached_at
    now = time.monotonic()
    if _catalog_cache is not None and now - _catalog_cached_at < _CATALOG_TTL_SECONDS:
        return _catalog_cache
    catalog = _fetch_openrouter_catalog_uncached()
    if catalog is not None:
        _catalog_cache = catalog
        _catalog_cached_at = now
    return catalog


def bot_prices_per_1m(bot_cfg, catalog):
    """Return (input_per_1m, output_per_1m) USD prices for a bot, or (None, None)
    if the bot is not OpenRouter-routed, the catalog is unavailable, or the model
    id is unresolved."""
    if catalog is None or not is_openrouter(bot_cfg):
        return None, None
    entry = catalog.get(bot_cfg.model or "")
    if not entry:
        return None, None
    pricing = entry.get("pricing", {})
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    input_price = float(prompt) * 1e6 if prompt is not None else None
    output_price = float(completion) * 1e6 if completion is not None else None
    return input_price, output_price


def fmt_price(price) -> str:
    """Format a per-1M price for display; '-' when unavailable."""
    return f"{price:.4g}" if price is not None else "-"
