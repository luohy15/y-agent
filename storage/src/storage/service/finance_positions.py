from __future__ import annotations

import datetime

from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_realtime_quote as realtime_quote_service


class ConversionError(ValueError):
    pass


def _today() -> datetime.date:
    return datetime.date.today()


def _parse_snapshot_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    return datetime.date.fromisoformat(value[:10])


def convert(amount: float, from_ccy: str, to_ccy: str, as_of: datetime.date | None) -> float:
    from_currency = from_ccy or to_ccy
    to_currency = to_ccy or from_currency
    if from_currency == to_currency:
        return amount
    price_date = as_of or _today()
    direct = price_service.latest_pair(from_currency, to_currency, price_date)
    if direct:
        return amount * float(direct.price)
    inverse = price_service.latest_pair(to_currency, from_currency, price_date)
    if inverse and inverse.price:
        return amount / float(inverse.price)
    raise ConversionError(f"No price found for {from_currency} -> {to_currency}")


def derive_positions(
    user_id: int,
    snapshot_date: str | None = None,
    risky_only: bool = False,
    base_currency: str = "USD",
) -> dict:
    holdings = holding_service.list_at(user_id, snapshot_date, risky_only=risky_only) if snapshot_date else holding_service.list_for(user_id, risky_only=risky_only)
    rows = holding_service.with_effective_values(holdings)
    _overlay_realtime_quotes(rows)
    base_values = []
    for holding, row in zip(holdings, rows):
        market_value = row.get("market_value")
        if market_value is None:
            base_values.append(None)
            continue
        currency = row.get("cost_currency") or row.get("symbol") or base_currency
        as_of = _parse_snapshot_date(row.get("snapshot_date") or getattr(holding, "snapshot_date", None)) or _today()
        base_values.append(convert(float(market_value), currency, base_currency, as_of))

    total_base_market_value = sum(value for value in base_values if value is not None)
    for row, base_value in zip(rows, base_values):
        row["allocation_base_currency"] = base_currency
        row["market_value_base"] = round(base_value, 2) if base_value is not None else None
        row["allocation_pct"] = round(base_value / total_base_market_value, 6) if base_value is not None and total_base_market_value else None

    return {"data": rows, "synced_at": holdings[0].synced_at if holdings else ""}


def _overlay_realtime_quotes(rows: list[dict]) -> None:
    """Override price / market_value / unrealized_profit_pct on USD rows with
    fresh Alpha Vantage realtime quotes. Adds `price_as_of` so the UI can show
    per-row freshness. Failures are silently skipped — the snapshot values
    remain visible."""
    symbols = sorted({
        row["symbol"]
        for row in rows
        if not row.get("is_cash")
        and row.get("symbol")
        and (row.get("cost_currency") or "").upper() == "USD"
        and row.get("quantity") is not None
    })
    if not symbols:
        return
    try:
        result = realtime_quote_service.fetch_bulk(symbols)
    except Exception:
        return
    for row in rows:
        symbol = row.get("symbol")
        quote = result.quotes.get(symbol) if symbol else None
        if quote is None:
            continue
        quantity = row.get("quantity")
        if quantity is None:
            continue
        live_market_value = float(quantity) * float(quote.close)
        row["price"] = float(quote.close)
        row["market_value"] = live_market_value
        row["price_as_of"] = quote.as_of.isoformat().replace("+00:00", "Z")
        book_value = row.get("book_value")
        if book_value not in (None, 0):
            row["unrealized_profit_pct"] = round((live_market_value - float(book_value)) / float(book_value) * 100, 4)
