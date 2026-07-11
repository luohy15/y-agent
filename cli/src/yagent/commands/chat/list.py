import click
import shutil
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options
from yagent.time_util import utc_to_local


def get_column_widths(weights: dict):
    total_weight = sum(weights.values())
    terminal_width = shutil.get_terminal_size().columns
    available_width = terminal_width - 10
    widths = [max(3, int(available_width * weight / total_weight)) for weight in weights.values()]
    return widths


@click.command('list')
@click.option('--limit', '-l', default=10, help='Maximum number of chats to show (default: 10)')
@click.option('--trace-id', default=None, help='Filter chats by trace_id (sorted oldest-first)')
@click.option('--routine', 'routine_id', default=None, help='Filter chats by routine_id')
@click.option('--routine-only', is_flag=True, default=False, help='Filter to chats triggered by any routine')
@time_filter_options
def list_chats(limit: int, trace_id: str, routine_id: str, routine_only: bool,
               on, from_, to, created_on, created_from, created_to,
               updated_on, updated_from, updated_to):
    """List chat conversations sorted by update time (newest first).

    Canonical time field: updated_at.
    """
    params = {"limit": limit}
    if trace_id:
        params["trace_id"] = trace_id
    if routine_id:
        params["routine_id"] = routine_id
    if routine_only:
        params["routine_only"] = True
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))
    resp = api_request("GET", "/api/chat/list", params=params)
    chats = resp.json()

    if not chats:
        click.echo("No chats found")
        return

    if trace_id:
        # Trace listing: chronological (oldest first) by created_at, surface
        # topic/skill so the caller can pick the right downstream chat.
        chats = sorted(chats, key=lambda c: c.get("created_at") or "")
        weights = {"ID": 2, "Topic": 2, "Skill": 2, "Created": 3}
        widths = get_column_widths(weights)
        table_data = [
            [
                chat["chat_id"],
                chat.get("topic") or "",
                chat.get("skill") or "",
                utc_to_local(chat["created_at"]),
            ]
            for chat in chats
        ]
        headers = ["ID", "Topic", "Skill", "Created"]
    elif routine_id or routine_only:
        # Routine listing: surface routine_id + topic so the caller can
        # confirm the dispatch target alongside the originating routine.
        weights = {"ID": 2, "Title": 4, "Topic": 2, "Routine": 2, "Updated": 3}
        widths = get_column_widths(weights)
        table_data = [
            [
                chat["chat_id"],
                chat["title"],
                chat.get("topic") or "",
                chat.get("routine_id") or "",
                utc_to_local(chat["updated_at"]),
            ]
            for chat in chats
        ]
        headers = ["ID", "Title", "Topic", "Routine", "Updated"]
    else:
        weights = {"ID": 1, "Title": 5, "Updated": 3}
        widths = get_column_widths(weights)
        table_data = [
            [
                chat["chat_id"],
                chat["title"],
                utc_to_local(chat["updated_at"]),
            ]
            for chat in chats
        ]
        headers = ["ID", "Title", "Updated"]

    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        maxcolwidths=widths,
        numalign='left',
        stralign='left'
    ))
