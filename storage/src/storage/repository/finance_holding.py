"""Function-based finance holding repository."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func

from storage.database.base import get_db
from storage.dto.finance_holding import FinanceHolding
from storage.entity.finance_holding import FinanceHoldingEntity
from storage.util import get_utc_iso8601_timestamp


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _day_bounds(snapshot_date: str) -> tuple[datetime, datetime]:
    day = date.fromisoformat(snapshot_date)
    start = datetime.combine(day, time.min).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _entity_to_dto(entity: FinanceHoldingEntity) -> FinanceHolding:
    snapshot_at = entity.snapshot_at
    if snapshot_at.tzinfo is None:
        snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)
    return FinanceHolding(
        id=entity.id,
        user_id=entity.user_id,
        snapshot_at=snapshot_at.isoformat(),
        snapshot_date=snapshot_at.date().isoformat(),
        symbol=entity.symbol,
        quantity=entity.quantity,
        average_cost=entity.average_cost,
        price=entity.price,
        book_value=entity.book_value,
        market_value=entity.market_value,
        unrealized_profit_pct=entity.unrealized_profit_pct,
        cost_currency=entity.cost_currency,
        is_cash=entity.is_cash,
        synced_at=entity.synced_at,
        source=entity.source,
    )


def _values(user_id: int, row: dict, synced_at: str, source: str, snapshot_at: datetime) -> dict:
    symbol = row.get("symbol") or ""
    cost_currency = row.get("cost_currency") or row.get("currency") or ""
    return dict(
        user_id=user_id,
        snapshot_at=_parse_datetime(row.get("snapshot_at") or snapshot_at),
        symbol=symbol,
        quantity=row.get("quantity") or 0,
        average_cost=row.get("average_cost"),
        price=row.get("price"),
        book_value=row.get("book_value"),
        market_value=row.get("market_value"),
        unrealized_profit_pct=row.get("unrealized_profit_pct"),
        cost_currency=cost_currency,
        is_cash=bool(row.get("is_cash", symbol == cost_currency)),
        synced_at=synced_at,
        source=source,
        updated_at=get_utc_iso8601_timestamp(),
    )


def append_snapshot(user_id: int, rows: list[dict], snapshot_at: str | datetime, synced_at: str, source: str = "sync") -> int:
    effective_snapshot_at = _parse_datetime(snapshot_at)
    with get_db() as session:
        if rows:
            session.bulk_insert_mappings(
                FinanceHoldingEntity,
                [_values(user_id, row, synced_at, source, effective_snapshot_at) for row in rows],
            )
        session.flush()
        return len(rows)


def latest_snapshot_at(user_id: int) -> Optional[datetime]:
    with get_db() as session:
        return session.query(func.max(FinanceHoldingEntity.snapshot_at)).filter_by(user_id=user_id).scalar()


def list_for(user_id: int) -> list[FinanceHolding]:
    snapshot_at = latest_snapshot_at(user_id)
    if not snapshot_at:
        return []
    with get_db() as session:
        rows = session.query(FinanceHoldingEntity).filter_by(user_id=user_id, snapshot_at=snapshot_at).order_by(FinanceHoldingEntity.market_value.desc().nullslast(), FinanceHoldingEntity.symbol.asc()).all()
        return [_entity_to_dto(row) for row in rows]


def list_at(user_id: int, snapshot_date: str) -> list[FinanceHolding]:
    start, end = _day_bounds(snapshot_date)
    with get_db() as session:
        latest = session.query(func.max(FinanceHoldingEntity.snapshot_at)).filter(
            FinanceHoldingEntity.user_id == user_id,
            FinanceHoldingEntity.snapshot_at >= start,
            FinanceHoldingEntity.snapshot_at < end,
        ).scalar()
        if not latest:
            return []
        rows = session.query(FinanceHoldingEntity).filter_by(user_id=user_id, snapshot_at=latest).order_by(FinanceHoldingEntity.market_value.desc().nullslast(), FinanceHoldingEntity.symbol.asc()).all()
        return [_entity_to_dto(row) for row in rows]
