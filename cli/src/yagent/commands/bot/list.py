import click
import shutil
from tabulate import tabulate
from yagent.config import config
from storage.service import bot_config as bot_service
from storage.service.user import get_current_user_id

def truncate_text(text, max_length):
    """Truncate text to max_length with ellipsis if needed."""
    if not text or len(str(text)) <= max_length:
        return text
    return str(text)[:max_length-3] + "..."

@click.command('list')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
def bot_list(verbose: bool = False):
    """List all bot configurations."""
    if verbose:
        click.echo(f"{click.style('Database:', fg='green')}\n{click.style(config['database_url'], fg='cyan')}")

    configs = bot_service.list_configs(get_current_user_id())

    if not configs:
        click.echo("No bot configurations found")
        return

    if verbose:
        click.echo(f"Found {len(configs)} bot configuration(s)")

    # Define column width ratios (total should be < 1 to leave space for separators)
    width_ratios = {
        "Name": 0.18,
        "API Key": 0.12,
        "API Type": 0.12,
        "Base URL": 0.18,
        "Model": 0.18,
        "Description": 0.18,
        "OpenRouter Config": 0.12
    }

    # Calculate actual column widths
    term_width = shutil.get_terminal_size().columns
    col_widths = {k: max(10, int(term_width * ratio)) for k, ratio in width_ratios.items()}

    # Prepare table data with truncated values
    table_data = []
    headers = ["Name", "API Key", "API Type", "Base URL", "Model", "Description", "OpenRouter Config"]

    for config in configs:
        table_data.append([
            truncate_text(config.name, col_widths["Name"]),
            truncate_text(config.api_key[:8] + "..." if config.api_key else "N/A", col_widths["API Key"]),
            truncate_text(config.api_type or "N/A", col_widths["API Type"]),
            truncate_text(config.base_url, col_widths["Base URL"]),
            truncate_text(config.model, col_widths["Model"]),
            truncate_text(config.description or "N/A", col_widths["Description"]),
            "Yes" if config.openrouter_config else "No"
        ])
    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        numalign='left',
        stralign='left'
    ))
