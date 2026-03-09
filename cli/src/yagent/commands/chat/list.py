import click
import shutil
from tabulate import tabulate

from yagent.api_client import api_request


def get_column_widths():
    weights = {"ID": 1, "Title": 5, "Updated": 3}
    total_weight = sum(weights.values())
    terminal_width = shutil.get_terminal_size().columns
    available_width = terminal_width - 10
    widths = [max(3, int(available_width * weight / total_weight)) for weight in weights.values()]
    return widths


@click.command('list')
@click.option('--limit', '-l', default=10, help='Maximum number of chats to show (default: 10)')
def list_chats(limit: int):
    """List chat conversations sorted by update time (newest first)."""
    resp = api_request("GET", "/api/chat/list", params={"limit": limit})
    chats = resp.json()

    if not chats:
        click.echo("No chats found")
        return

    widths = get_column_widths()

    table_data = []
    for chat in chats:
        table_data.append([
            chat["chat_id"],
            chat["title"],
            chat["updated_at"],
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
