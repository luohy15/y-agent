import click

from storage.service import finance_transaction as transaction_service

from ._helpers import echo_json, resolve_user_id


@click.command("transactions")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read transactions for")
@click.option("--symbol", default=None, help="Optional symbol filter")
@click.option("--limit", type=int, default=500, help="Maximum number of entries to return")
def transactions(user_id: int | None, symbol: str | None, limit: int):
    """Read DB-backed finance transactions as JSON."""
    rows = transaction_service.list_entries_for(resolve_user_id(user_id), symbol=symbol, limit=limit)
    synced_at = rows[0].get("synced_at", "") if rows else ""
    echo_json({"data": rows, "synced_at": synced_at, "source": "db"})
