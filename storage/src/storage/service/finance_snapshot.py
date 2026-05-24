"""Finance snapshot service."""

from datetime import datetime, timezone
from typing import Any, Optional

from storage.dto.finance_snapshot import FinanceSnapshot
from storage.repository import finance_snapshot as snapshot_repo
from storage.util import get_utc_iso8601_timestamp


STALE_AFTER_SECONDS = 30 * 60


def get_or_none(
    user_id: int,
    vm_name: str,
    view: str,
    time_filter: str = "",
    history: bool = False,
    granularity: str = "",
    convert: str = "",
) -> Optional[FinanceSnapshot]:
    return snapshot_repo.lookup(user_id, vm_name, view, time_filter, history, granularity, convert)


def is_fresh(snapshot: FinanceSnapshot, stale_after_seconds: int = STALE_AFTER_SECONDS) -> bool:
    try:
        synced_at = datetime.fromisoformat(snapshot.synced_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - synced_at).total_seconds() < stale_after_seconds


def upsert_payload(
    user_id: int,
    vm_name: str,
    view: str,
    payload: Any,
    synced_at: Optional[str] = None,
    source: str = "sync",
    time_filter: str = "",
    history: bool = False,
    granularity: str = "",
    convert: str = "",
) -> FinanceSnapshot:
    return snapshot_repo.upsert(
        user_id=user_id,
        vm_name=vm_name,
        view=view,
        payload=payload,
        synced_at=synced_at or get_utc_iso8601_timestamp(),
        source=source,
        time_filter=time_filter,
        history=history,
        granularity=granularity,
        convert=convert,
    )


def invalidate_user(user_id: int, vm_name: str = "") -> int:
    return snapshot_repo.delete_for_user(user_id, vm_name)
