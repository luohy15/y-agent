from storage.repository import finance_transaction as repo
from storage.util import get_utc_iso8601_timestamp


def _sum_by_currency(rows, value_attr: str, currency_attr: str, fallback_attr: str = "symbol") -> list[dict]:
    totals: dict[str, float] = {}
    for row in rows:
        value = getattr(row, value_attr)
        if value is None:
            continue
        currency = getattr(row, currency_attr) or getattr(row, fallback_attr) or ""
        totals[currency] = totals.get(currency, 0.0) + float(value)
    return [{"amount": amount, "currency": currency} for currency, amount in totals.items()]


def entry_rows(rows):
    by_entry: dict[str, dict] = {}
    grouped_rows: dict[str, list] = {}
    for row in rows:
        entry_id = row.entry_id or f"{row.transaction_date}:{row.payee}:{row.narration}"
        entry = by_entry.setdefault(entry_id, {
            "transaction_date": row.transaction_date,
            "entry_id": entry_id,
            "symbols": [],
            "sides": [],
            "postings": [],
            "payee": row.payee,
            "narration": row.narration,
            "synced_at": row.synced_at,
            "source": row.source,
        })
        grouped_rows.setdefault(entry_id, []).append(row)
        entry["postings"].append(row.to_dict())
        if row.symbol and row.symbol not in entry["symbols"]:
            entry["symbols"].append(row.symbol)
        if row.side and row.side != "Unknown" and row.side not in entry["sides"]:
            entry["sides"].append(row.side)
        if not entry["payee"] and row.payee:
            entry["payee"] = row.payee
        if not entry["narration"] and row.narration:
            entry["narration"] = row.narration
    for entry_id, entry in by_entry.items():
        rows_for_entry = grouped_rows[entry_id]
        entry["symbol"] = ", ".join(entry["symbols"])
        entry["side"] = ", ".join(entry["sides"]) or "Unknown"
        entry["quantity"] = _sum_by_currency(rows_for_entry, "quantity", "symbol")
        entry["amount"] = _sum_by_currency(rows_for_entry, "amount", "amount_currency")
        entry["price"] = None
        entry["price_currency"] = ""
        entry["commission"] = None
        entry["commission_currency"] = ""
    return list(by_entry.values())


def replace_for(user_id: int, vm_name: str, rows: list[dict], synced_at: str | None = None, source: str = "sync") -> int:
    return repo.replace_for(user_id, vm_name, rows, synced_at or get_utc_iso8601_timestamp(), source)


def list_for(user_id: int, vm_name: str, symbol: str | None = None, limit: int = 500):
    return repo.list_for(user_id, vm_name, symbol=symbol, limit=limit)


def list_entries_for(user_id: int, vm_name: str, symbol: str | None = None, limit: int = 500):
    return entry_rows(repo.list_for(user_id, vm_name, symbol=symbol, limit=limit))


def list_between(user_id: int, vm_name: str, start_date=None, end_date=None):
    return repo.list_between(user_id, vm_name, start_date=start_date, end_date=end_date)


def latest_synced_at(user_id: int, vm_name: str) -> str:
    return repo.latest_synced_at(user_id, vm_name)
