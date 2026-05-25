from storage.repository import finance_transaction as repo
from storage.util import get_utc_iso8601_timestamp


def replace_for(user_id: int, vm_name: str, rows: list[dict], synced_at: str | None = None, source: str = "sync") -> int:
    return repo.replace_for(user_id, vm_name, rows, synced_at or get_utc_iso8601_timestamp(), source)


def list_for(user_id: int, vm_name: str, symbol: str | None = None, limit: int = 500):
    return repo.list_for(user_id, vm_name, symbol=symbol, limit=limit)


def list_between(user_id: int, vm_name: str, start_date=None, end_date=None):
    return repo.list_between(user_id, vm_name, start_date=start_date, end_date=end_date)


def latest_synced_at(user_id: int, vm_name: str) -> str:
    return repo.latest_synced_at(user_id, vm_name)
