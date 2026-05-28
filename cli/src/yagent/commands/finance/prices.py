import click

from storage.service import finance_derived as derived_service
from storage.service import finance_price as price_service

from ._helpers import echo_json, rows_envelope


@click.command("prices")
@click.option("--symbol", default=None, help="Optional symbol filter")
@click.option("--time", default="year to day-1", help="Time filter (e.g. ytd, 1y, 2024, day-30 to day-1)")
@click.option("--limit", type=int, default=1000, help="Maximum number of price rows to return")
def prices(symbol: str | None, time: str, limit: int):
    """Read DB-backed finance prices as JSON."""
    from_date, to_date = derived_service.parse_time_range(time)
    rows = price_service.list_for(
        symbol=symbol,
        from_date=str(from_date) if from_date else None,
        to_date=str(to_date) if to_date else None,
        limit=limit,
    )
    echo_json(rows_envelope(rows))
