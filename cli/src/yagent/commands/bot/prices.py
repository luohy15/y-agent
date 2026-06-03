import json
from datetime import datetime, timezone

import click
import httpx
from tabulate import tabulate

from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def _is_openrouter(bot_cfg) -> bool:
    """A bot routes through OpenRouter if its base_url targets the OpenRouter API
    (directly or via the Cloudflare AI gateway '.../openrouter' endpoint)."""
    return "openrouter" in (bot_cfg.base_url or "").lower()


@click.command("prices")
@click.option("--json", "as_json", is_flag=True, help="Output the raw JSON rows instead of a table")
def bot_prices(as_json: bool):
    """Show OpenRouter input/output prices (USD per 1M tokens) for each bot."""
    configs = bot_service.list_configs(get_cli_user_id())
    or_bots = [c for c in configs if _is_openrouter(c)]

    if not or_bots:
        click.echo("No OpenRouter bots found")
        return

    try:
        resp = httpx.get(OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        catalog = {m["id"]: m for m in resp.json()["data"]}
    except Exception as err:
        click.echo(f"Failed to fetch OpenRouter prices: {err}")
        return

    rows = []
    for bot_cfg in or_bots:
        model = bot_cfg.model or ""
        entry = catalog.get(model)
        pricing = entry.get("pricing", {}) if entry else {}
        prompt = pricing.get("prompt")
        completion = pricing.get("completion")
        input_price = float(prompt) * 1e6 if prompt is not None else None
        output_price = float(completion) * 1e6 if completion is not None else None
        rows.append({
            "bot": bot_cfg.name,
            "model": model,
            "input_per_1m": input_price,
            "output_per_1m": output_price,
        })

    if as_json:
        synced_at = datetime.now(timezone.utc).isoformat()
        click.echo(json.dumps({"data": rows, "synced_at": synced_at, "source": "openrouter"}))
        return

    def fmt(price):
        return f"{price:.4g}" if price is not None else "not found"

    table_data = [
        [r["bot"], r["model"], fmt(r["input_per_1m"]), fmt(r["output_per_1m"])]
        for r in rows
    ]
    click.echo(tabulate(
        table_data,
        headers=["Bot", "Model", "Input/1M", "Output/1M"],
        tablefmt="simple",
        numalign="left",
        stralign="left",
    ))
