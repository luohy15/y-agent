import click
import shutil
from tabulate import tabulate
from storage.entity.dto import BotConfig
from storage.service.bot_pricing import fmt_price
from yagent.api_client import api_request
from .tier import display_tier

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
    rows = api_request("GET", "/api/bot/list").json()

    if filter_type:
        rows = [r for r in rows if (r.get('type') or 'agent') == filter_type]

    if not rows:
        click.echo("No bot configurations found")
        return

    by_name = {r['name']: BotConfig(name=r['name'], tier=r.get('tier'), ref_bot_name=r.get('ref_bot_name')) for r in rows}

    if full:
        # Full table: all columns
        width_ratios = {
            "Name": 0.15,
            "API Key": 0.10,
            "Backend": 0.10,
            "Base URL": 0.15,
            "Model": 0.15,
            "Description": 0.15,
            "OpenRouter Config": 0.10,
            "Ref": 0.10,
        }
        term_width = shutil.get_terminal_size().columns
        col_widths = {k: max(10, int(term_width * ratio)) for k, ratio in width_ratios.items()}

        headers = ["Name", "API Key", "Backend", "Base URL", "Model", "Description",
                   "OpenRouter Config", "Ref", "Input/1M", "Output/1M", "Tier", "Type", "Enabled"]
        table_data = []
        for r in rows:
            table_data.append([
                truncate_text(r['name'], col_widths["Name"]),
                truncate_text(r.get('api_key_masked') or "N/A", col_widths["API Key"]),
                truncate_text(r.get('backend') or "N/A", col_widths["Backend"]),
                truncate_text(r.get('base_url'), col_widths["Base URL"]),
                truncate_text(r.get('model'), col_widths["Model"]),
                truncate_text(r.get('description') or "N/A", col_widths["Description"]),
                "Yes" if r.get('has_openrouter') else "No",
                r.get('ref_bot_name') or "-",
                fmt_price(r.get('price_input')),
                fmt_price(r.get('price_output')),
                display_tier(by_name[r['name']], lambda n: by_name.get(n)),
                r.get('type') or "agent",
                "Yes" if r.get('enabled') else "No",
            ])
    else:
        # Compact: Name, Backend, Model, Tier, Type, Ref
        headers = ["Name", "Backend", "Model", "Tier", "Type", "Ref"]
        table_data = []
        for r in rows:
            table_data.append([
                r['name'],
                r.get('backend') or "N/A",
                r.get('model') or "N/A",
                display_tier(by_name[r['name']], lambda n: by_name.get(n)),
                r.get('type') or "agent",
                r.get('ref_bot_name') or "-",
            ])

    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        numalign='left',
        stralign='left'
    ))
