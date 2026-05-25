from storage.repository import finance_price as repo
from storage.util import get_utc_iso8601_timestamp


def replace_for(user_id: int, vm_name: str, rows: list[dict], synced_at: str | None = None, source: str = "sync") -> int:
    return repo.replace_for(user_id, vm_name, rows, synced_at or get_utc_iso8601_timestamp(), source)


def list_for(user_id: int, vm_name: str, symbol: str | None = None, from_date: str | None = None, to_date: str | None = None, limit: int = 1000):
    return repo.list_for(user_id, vm_name, symbol=symbol, from_date=from_date, to_date=to_date, limit=limit)


def latest_pair(user_id: int, vm_name: str, symbol: str, currency: str, as_of):
    return repo.latest_pair(user_id, vm_name, symbol, currency, as_of)


def list_for_pairs(user_id: int, vm_name: str, pairs: set[tuple[str, str]], as_of):
    return repo.list_for_pairs(user_id, vm_name, pairs, as_of)
