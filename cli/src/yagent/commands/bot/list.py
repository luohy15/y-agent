import click
import shutil
from tabulate import tabulate
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from storage.service.bot_pricing import fetch_openrouter_catalog, bot_prices_per_1m, fmt_price

def truncate_text(text, max_length):
    """Truncate text to max_length with ellipsis if needed."""
    if not text or len(str(text)) <= max_length:
        return text
    return str(text)[:max_length-3] + "..."

@click.command('list')
@click.option('--full', '-f', is_flag=True, help='Show all columns (full table)')
@click.option('--type', '-t', 'filter_type', type=click.Choice(['agent', 'model']), help='Filter by type')
def bot_list(full: bool = False, filter_type: str | None = None):
    """List all bot configurations (compact by default)."""
    configs = bot_service.list_configs(get_cli_user_id())

    if filter_type:
        configs = [c for c in configs if (c.type or 'agent') == filter_type]

    if not configs:
        click.echo("No bot configurations found")
        return

    if full:
        # Full table: all columns
        width_ratios = {
            "Name": 0.18,
            "API Key": 0.12,
            "Backend": 0.12,
            "Base URL": 0.18,
            "Model": 0.18,
            "Description": 0.18,
            "OpenRouter Config": 0.12
        }
        term_width = shutil.get_terminal_size().columns
        col_widths = {k: max(10, int(term_width * ratio)) for k, ratio in width_ratios.items()}
        catalog = fetch_openrouter_catalog()

        headers = ["Name", "API Key", "Backend", "Base URL", "Model", "Description",
                   "OpenRouter Config", "Input/1M", "Output/1M", "Tier", "Type", "Enabled"]
        table_data = []
        for bot_cfg in configs:
            input_price, output_price = bot_prices_per_1m(bot_cfg, catalog)
            table_data.append([
                truncate_text(bot_cfg.name, col_widths["Name"]),
                truncate_text(bot_cfg.api_key[:8] + "..." if bot_cfg.api_key else "N/A", col_widths["API Key"]),
                truncate_text(bot_cfg.backend or bot_cfg.api_type or "N/A", col_widths["Backend"]),
                truncate_text(bot_cfg.base_url, col_widths["Base URL"]),
                truncate_text(bot_cfg.model, col_widths["Model"]),
                truncate_text(bot_cfg.description or "N/A", col_widths["Description"]),
                "Yes" if bot_cfg.openrouter_config else "No",
                fmt_price(input_price),
                fmt_price(output_price),
                bot_cfg.tier or "tier1",
                bot_cfg.type or "agent",
                "Yes" if bot_cfg.enabled else "No",
            ])
    else:
        # Compact: Name, Backend, Model, Type
        headers = ["Name", "Backend", "Model", "Type"]
        table_data = []
        for bot_cfg in configs:
            table_data.append([
                bot_cfg.name,
                bot_cfg.backend or bot_cfg.api_type or "N/A",
                bot_cfg.model or "N/A",
                bot_cfg.type or "agent",
            ])

    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        numalign='left',
        stralign='left'
    ))
