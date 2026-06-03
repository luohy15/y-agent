"""Best-effort OpenRouter price lookup shared by `y bot list` / `y bot get`.

Prices come from the public OpenRouter model catalog (no auth). Fetch once per
command invocation via `fetch_openrouter_catalog()`, then resolve each bot with
`bot_prices_per_1m()`."""

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def is_openrouter(bot_cfg) -> bool:
    """A bot routes through OpenRouter if its base_url targets the OpenRouter API
    (directly or via the Cloudflare AI gateway '.../openrouter' endpoint)."""
    return "openrouter" in (bot_cfg.base_url or "").lower()


def fetch_openrouter_catalog():
    """Fetch the public OpenRouter model catalog once. Best-effort: returns a
    {model_id: model} dict, or None if the request fails (offline / non-200)."""
    try:
        resp = httpx.get(OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        return {m["id"]: m for m in resp.json()["data"]}
    except Exception:
        return None


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
