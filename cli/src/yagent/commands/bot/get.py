import click
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from storage.service.bot_pricing import fetch_openrouter_catalog, bot_prices_per_1m, fmt_price

@click.command('get')
@click.argument('name')
def bot_get(name):
    """Show full details of a single bot configuration."""
    config = bot_service.get_config(get_cli_user_id(), name=name)
    if config is None or config.name != name:
        click.echo(f"Bot '{name}' not found")
        return

    input_price, output_price = bot_prices_per_1m(config, fetch_openrouter_catalog())

    fields = [
        ("Name", config.name),
        ("Backend", config.backend or config.api_type or "N/A"),
        ("Base URL", config.base_url),
        ("Model", config.model or "N/A"),
        ("API Key", config.api_key or "N/A"),
        ("Description", config.description or "N/A"),
        ("OpenRouter Config", config.openrouter_config or "N/A"),
        ("Input/1M", fmt_price(input_price)),
        ("Output/1M", fmt_price(output_price)),
    ]
    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        click.echo(f"{click.style(label.ljust(width), fg='green')}  {value}")
