import json

import click

from storage.service.finance_positions import derive_positions
from storage.service.user import get_cli_user_id


@click.command("positions")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read positions for")
@click.option("--at", "snapshot_date", default=None, help="Snapshot date to read (YYYY-MM-DD); defaults to latest")
@click.option("--risky-only", is_flag=True, help="Only include risky holdings")
@click.option("--base-currency", default="USD", help="Currency for allocation and market_value_base")
def positions(user_id: int | None, snapshot_date: str | None, risky_only: bool, base_currency: str):
    """Read DB-backed finance positions as JSON."""
    target_user_id = user_id or get_cli_user_id()
    result = derive_positions(
        target_user_id,
        snapshot_date=snapshot_date,
        risky_only=risky_only,
        base_currency=base_currency,
    )
    click.echo(json.dumps({"data": result["data"], "synced_at": result["synced_at"], "source": "db"}))
