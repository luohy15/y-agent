import click

from storage.service import finance_fundamentals as fundamentals_service

from ._helpers import echo_json, json_option
from ._render import render_fundamentals


@click.command("fundamentals")
@click.argument("symbol")
@json_option
def fundamentals(symbol: str, as_json: bool):
    """Company fundamentals (Alpha Vantage cache) for a ticker.

    Table by default; --json emits the full envelope (including the raw Alpha Vantage
    statement bodies) matching GET /api/finance/fundamentals?include_raw=true.
    """
    normalized = (symbol or "").strip().upper()
    if not normalized:
        raise click.UsageError("symbol is required")
    if not fundamentals_service.api_key():
        raise click.ClickException("ALPHAVANTAGE_API_KEY is not configured")
    result = fundamentals_service.fetch(normalized)
    if as_json:
        echo_json(result.to_envelope(include_raw=True))
    else:
        render_fundamentals(result.to_envelope())
