"""Function-based finance snapshot repository using SQLAlchemy sessions."""

from typing import Any, Optional

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.dto.finance_snapshot import FinanceSnapshot
from storage.entity.finance_snapshot import FinanceSnapshotEntity
from storage.util import get_utc_iso8601_timestamp


def _history_key(history: bool) -> str:
    return "true" if history else "false"


def _entity_to_dto(entity: FinanceSnapshotEntity) -> FinanceSnapshot:
    return FinanceSnapshot(
        id=entity.id,
        user_id=entity.user_id,
        vm_name=entity.vm_name,
        view=entity.view,
        time_filter=entity.time_filter,
        history=entity.history == "true",
        granularity=entity.granularity,
        convert=entity.convert,
        payload=entity.payload,
        synced_at=entity.synced_at,
        source=entity.source,
        last_error=entity.last_error,
    )


def lookup(
    user_id: int,
    vm_name: str,
    view: str,
    time_filter: str = "",
    history: bool = False,
    granularity: str = "",
    convert: str = "",
) -> Optional[FinanceSnapshot]:
    with get_db() as session:
        row = session.query(FinanceSnapshotEntity).filter_by(
            user_id=user_id,
            vm_name=vm_name or "",
            view=view,
            time_filter=time_filter or "",
            history=_history_key(history),
            granularity=granularity or "",
            convert=convert or "",
        ).first()
        if row:
            return _entity_to_dto(row)
        return None


def upsert(
    user_id: int,
    vm_name: str,
    view: str,
    payload: Any,
    synced_at: str,
    source: str = "sync",
    time_filter: str = "",
    history: bool = False,
    granularity: str = "",
    convert: str = "",
    last_error: Optional[str] = None,
) -> FinanceSnapshot:
    values = dict(
        user_id=user_id,
        vm_name=vm_name or "",
        view=view,
        time_filter=time_filter or "",
        history=_history_key(history),
        granularity=granularity or "",
        convert=convert or "",
        payload=payload,
        synced_at=synced_at,
        source=source,
        last_error=last_error,
        updated_at=get_utc_iso8601_timestamp(),
    )
    with get_db() as session:
        stmt = insert(FinanceSnapshotEntity).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_finance_snapshot_key",
            set_={
                "payload": stmt.excluded.payload,
                "synced_at": stmt.excluded.synced_at,
                "source": stmt.excluded.source,
                "last_error": stmt.excluded.last_error,
                "updated_at": stmt.excluded.updated_at,
            },
        ).returning(FinanceSnapshotEntity)
        row = session.execute(stmt).scalar_one()
        session.flush()
        return _entity_to_dto(row)


def delete_for_user(user_id: int, vm_name: str = "") -> int:
    with get_db() as session:
        count = session.query(FinanceSnapshotEntity).filter_by(
            user_id=user_id,
            vm_name=vm_name or "",
        ).delete()
        session.flush()
        return count
