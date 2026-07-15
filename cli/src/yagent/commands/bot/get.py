import click
import httpx
from storage.entity.dto import BotConfig
from storage.service.bot_pricing import fmt_price
from yagent.api_client import api_request
from .tier import display_tier

@click.command('get')
@click.argument('name')
def bot_get(name):
    """Show full details of a single bot configuration."""
    try:
        config = api_request("GET", "/api/bot/config", params={"name": name}).json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Bot '{name}' not found")
            return
        raise

    rows = api_request("GET", "/api/bot/list").json()
    by_name = {r['name']: BotConfig(name=r['name'], tier=r.get('tier'), ref_bot_name=r.get('ref_bot_name')) for r in rows}
    cur = by_name.get(name) or BotConfig(name=config['name'], tier=config.get('tier'), ref_bot_name=config.get('ref_bot_name'))

    fields = [
        ("Name", config['name']),
        ("Backend", config.get('backend') or "N/A"),
        ("Base URL", config.get('base_url')),
        ("Model", config.get('model') or "N/A"),
        ("API Key", config.get('api_key_masked') or "N/A"),
        ("Description", config.get('description') or "N/A"),
        ("OpenRouter Config", "Yes" if config.get('has_openrouter') else "N/A"),
        ("Input/1M", fmt_price(config.get('price_input'))),
        ("Output/1M", fmt_price(config.get('price_output'))),
        ("Tier", display_tier(cur, lambda n: by_name.get(n))),
        ("Type", config.get('type') or "agent"),
        ("Route Weight", config.get('route_weight') if config.get('route_weight') is not None else "N/A"),
        ("Ref", config.get('ref_bot_name') or "N/A"),
        ("Enabled", "Yes" if config.get('enabled') else "No"),
    ]
    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        click.echo(f"{click.style(label.ljust(width), fg='green')}  {value}")
