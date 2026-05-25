from datetime import datetime, timezone

from storage.repository import finance_holding as repo
from storage.util import get_utc_iso8601_timestamp


NON_RISKY_TICKERS = {"CASH", "BOXX"}


def _effective_market_value(row) -> float | None:
    if row.market_value is not None:
        return row.market_value
    if row.is_cash or row.symbol == row.cost_currency:
        return row.quantity
    return None


def is_risky_holding(row) -> bool:
    if row.is_cash:
        return False
    if row.symbol in NON_RISKY_TICKERS:
        return False
    if row.market_value is not None and row.symbol == row.cost_currency:
        return False
    return True


def should_show_holding(row, risky_only: bool = False) -> bool:
    if abs(row.quantity or 0) <= 0.005:
        return False
    market_value = _effective_market_value(row)
    if market_value is not None and abs(market_value) <= 0.005:
        return False
    return not risky_only or is_risky_holding(row)


def filter_holdings(rows, risky_only: bool = False):
    return [row for row in rows if should_show_holding(row, risky_only)]


def with_effective_values(rows):
    result = []
    for row in rows:
        data = row.to_dict()
        market_value = _effective_market_value(row)
        if market_value is not None:
            data["market_value"] = market_value
        if data.get("book_value") is None and (row.is_cash or row.symbol == row.cost_currency):
            data["book_value"] = market_value
        result.append(data)
    return result


def _amount(value):
    if isinstance(value, dict):
        return value.get("number"), value.get("currency") or ""
    if isinstance(value, (int, float)):
        return float(value), ""
    return None, ""


def rows_from_holdings_payload(payload: dict) -> list[dict]:
    rows = []
    for row in payload.get("rows", []):
        units, symbol = _amount(row.get("units"))
        average_cost, avg_currency = _amount(row.get("average_cost"))
        price, price_currency = _amount(row.get("price"))
        book_value, book_currency = _amount(row.get("book_value"))
        market_value, market_currency = _amount(row.get("market_value"))
        cost_currency = book_currency or market_currency or avg_currency or price_currency or symbol
        rows.append({
            "symbol": symbol,
            "quantity": units or 0,
            "average_cost": average_cost,
            "price": price,
            "book_value": book_value,
            "market_value": market_value,
            "unrealized_profit_pct": row.get("unrealized_profit_pct"),
            "cost_currency": cost_currency,
            "is_cash": symbol == cost_currency,
        })
    return rows


def append_snapshot(user_id: int, vm_name: str, rows: list[dict], snapshot_at: str | datetime | None = None, synced_at: str | None = None, source: str = "sync") -> int:
    effective_synced_at = synced_at or get_utc_iso8601_timestamp()
    return repo.append_snapshot(user_id, vm_name, rows, snapshot_at or datetime.now(timezone.utc), effective_synced_at, source)


def list_for(user_id: int, vm_name: str, risky_only: bool = False):
    return filter_holdings(repo.list_for(user_id, vm_name), risky_only=risky_only)


def list_at(user_id: int, vm_name: str, snapshot_date: str, risky_only: bool = False):
    return filter_holdings(repo.list_at(user_id, vm_name, snapshot_date), risky_only=risky_only)
