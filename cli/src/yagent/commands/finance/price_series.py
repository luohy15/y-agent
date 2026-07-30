import click

from storage.service import finance_price_series as price_series_service

from ._helpers import echo_json, json_option
from ._render import render_price_series


@click.command("price-series")
@click.argument("symbol")
@click.option("--range", "range_token", default="ytd", help="Range token: 1w, 1m, 3m, ytd, 1y, 5y, all")
@json_option
def price_series(symbol: str, range_token: str, as_json: bool):
    """Live Alpha Vantage price series for the ticker chart (mirror of GET /api/finance/price-series).

    Pure pass-through: no caching, every call issues one upstream request. Table by
    default; --json emits the raw envelope.
    """
    normalized = (symbol or "").strip().upper()
    if not normalized:
        raise click.UsageError("symbol is required")
    normalized_range = (range_token or "").strip().lower()
    if normalized_range not in price_series_service.RANGE_TABLE:
        raise click.UsageError(f"range must be one of: {', '.join(price_series_service.RANGE_TABLE)}")
    try:
        result = price_series_service.fetch(normalized, normalized_range)
    except price_series_service.PriceSeriesError as exc:
        raise click.ClickException(str(exc))
    envelope = result.to_envelope()
    if as_json:
        echo_json(envelope)
    else:
        render_price_series(envelope)
