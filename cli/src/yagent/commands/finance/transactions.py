import click

from storage.service import finance_transaction as transaction_service

from ._helpers import echo_json, json_option, resolve_user_id
from ._render import render_transactions


@click.command("transactions")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read transactions for")
@click.option("--symbol", default=None, help="Optional symbol filter")
@click.option("--limit", type=int, default=500, help="Maximum number of entries to return")
@json_option
def transactions(user_id: int | None, symbol: str | None, limit: int, as_json: bool):
    """Read DB-backed finance transactions (table by default; --json for the raw envelope)."""
    rows = transaction_service.list_entries_for(resolve_user_id(user_id), symbol=symbol, limit=limit)
    synced_at = rows[0].get("synced_at", "") if rows else ""
    envelope = {"data": rows, "synced_at": synced_at, "source": "db"}
    if as_json:
        echo_json(envelope)
    else:
        render_transactions(envelope)
