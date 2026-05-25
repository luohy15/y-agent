"""Function-based finance price repository."""

from datetime import date
from typing import Optional

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.dto.finance_price import FinancePrice
from storage.entity.finance_price import FinancePriceEntity
from storage.util import get_utc_iso8601_timestamp


def _entity_to_dto(entity: FinancePriceEntity) -> FinancePrice:
    return FinancePrice(
        id=entity.id,
        user_id=entity.user_id,
        vm_name=entity.vm_name,
        symbol=entity.symbol,
        price_date=str(entity.price_date),
        price=entity.price,
        currency=entity.currency,
        synced_at=entity.synced_at,
        source=entity.source,
    )


def _values(user_id: int, vm_name: str, row: dict, synced_at: str, source: str) -> dict:
    return dict(
        user_id=user_id,
        vm_name=vm_name or "",
        symbol=row.get("symbol") or "",
        price_date=row.get("price_date") or row.get("date"),
        price=row.get("price"),
        currency=row.get("currency") or "",
        synced_at=synced_at,
        source=source,
        updated_at=get_utc_iso8601_timestamp(),
    )


def replace_for(user_id: int, vm_name: str, rows: list[dict], synced_at: str, source: str = "sync") -> int:
    effective_vm_name = vm_name or ""
    with get_db() as session:
        session.query(FinancePriceEntity).filter_by(user_id=user_id, vm_name=effective_vm_name).delete()
        if rows:
            for row in rows:
                stmt = insert(FinancePriceEntity).values(**_values(user_id, effective_vm_name, row, synced_at, source))
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_finance_price_daily",
                    set_={"price": stmt.excluded.price, "synced_at": stmt.excluded.synced_at, "source": stmt.excluded.source, "updated_at": stmt.excluded.updated_at},
                )
                session.execute(stmt)
        session.flush()
        return len(rows)


def list_for(user_id: int, vm_name: str, symbol: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None, limit: int = 1000) -> list[FinancePrice]:
    parsed_from_date = date.fromisoformat(from_date) if from_date else None
    parsed_to_date = date.fromisoformat(to_date) if to_date else None
    with get_db() as session:
        query = session.query(FinancePriceEntity).filter_by(user_id=user_id, vm_name=vm_name or "")
        if symbol:
            query = query.filter_by(symbol=symbol)
        if parsed_from_date:
            query = query.filter(FinancePriceEntity.price_date >= parsed_from_date)
        if parsed_to_date:
            query = query.filter(FinancePriceEntity.price_date <= parsed_to_date)
        rows = query.order_by(FinancePriceEntity.symbol.asc(), FinancePriceEntity.price_date.asc()).limit(limit).all()
        return [_entity_to_dto(row) for row in rows]


def latest_pair(user_id: int, vm_name: str, symbol: str, currency: str, as_of: date) -> FinancePrice | None:
    with get_db() as session:
        row = session.query(FinancePriceEntity).filter_by(user_id=user_id, vm_name=vm_name or "", symbol=symbol, currency=currency).filter(FinancePriceEntity.price_date <= as_of).order_by(FinancePriceEntity.price_date.desc()).first()
        return _entity_to_dto(row) if row else None
