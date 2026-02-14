import click
import shutil
from tabulate import tabulate


def get_column_widths():
    weights = {"ID": 1, "Title": 5, "Updated": 3}
    total_weight = sum(weights.values())
    terminal_width = shutil.get_terminal_size().columns
    available_width = terminal_width - 10
    widths = [max(3, int(available_width * weight / total_weight)) for weight in weights.values()]
    return widths


@click.command('list')
@click.option('--limit', '-l', default=10, help='Maximum number of chats to show (default: 10)')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
def list_chats(limit: int, verbose: bool = False):
    """List chat conversations sorted by update time (newest first)."""
    from yagent.config import config
    if verbose:
        click.echo(f"{click.style('Database:', fg='green')}\n{click.style(config['database_url'], fg='cyan')}")
        click.echo(f"Result limit: {limit}")
    import asyncio

    from storage.service import chat as chat_service
    from storage.service.user import get_cli_user_id
    chats = asyncio.run(chat_service.list_chats(get_cli_user_id(), limit=limit))
    if not chats:
        click.echo("No chats found")
        return

    if verbose:
        click.echo(f"Found {len(chats)} chat(s)")

    widths = get_column_widths()

    table_data = []
    for chat in chats:
        table_data.append([
            chat.chat_id,
            chat.title,
            chat.updated_at,
        ])

    headers = ["ID", "Title", "Updated"]
    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        maxcolwidths=widths,
        numalign='left',
        stralign='left'
    ))
