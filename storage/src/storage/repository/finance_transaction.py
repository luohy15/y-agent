"""Function-based finance transaction repository."""

from datetime import date
from typing import Optional

from storage.database.base import get_db
from storage.dto.finance_transaction import FinanceTransaction
from storage.entity.finance_transaction import FinanceTransactionEntity
from storage.util import get_utc_iso8601_timestamp


def _entity_to_dto(entity: FinanceTransactionEntity) -> FinanceTransaction:
    return FinanceTransaction(
        id=entity.id,
        user_id=entity.user_id,
        transaction_date=str(entity.transaction_date),
        entry_id=entity.entry_id,
        posting_index=entity.posting_index,
        account=entity.account,
        symbol=entity.symbol,
        side=entity.side,
        quantity=entity.quantity,
        price=entity.price,
        price_currency=entity.price_currency,
        amount=entity.amount,
        amount_currency=entity.amount_currency,
        cost=entity.cost,
        cost_currency=entity.cost_currency,
        commission=entity.commission,
        commission_currency=entity.commission_currency,
        payee=entity.payee,
        narration=entity.narration,
        tags=list(entity.tags or []),
        links=list(entity.links or []),
        synced_at=entity.synced_at,
        source=entity.source,
    )


def _values(user_id: int, row: dict, synced_at: str, source: str) -> dict:
    return dict(
        user_id=user_id,
        transaction_date=row.get("transaction_date") or row.get("date"),
        entry_id=row.get("entry_id") or row.get("id"),
        posting_index=int(row.get("posting_index") or 0),
        account=row.get("account") or "",
        symbol=row.get("symbol") or "",
        side=row.get("side") or "Unknown",
        quantity=row.get("quantity"),
        price=row.get("price"),
        price_currency=row.get("price_currency") or "",
        amount=row.get("amount"),
        amount_currency=row.get("amount_currency") or "",
        cost=row.get("cost"),
        cost_currency=row.get("cost_currency") or "",
        commission=row.get("commission"),
        commission_currency=row.get("commission_currency") or "",
        payee=row.get("payee") or "",
        narration=row.get("narration") or "",
        tags=list(row.get("tags") or []),
        links=list(row.get("links") or []),
        synced_at=synced_at,
        source=source,
        updated_at=get_utc_iso8601_timestamp(),
    )


def replace_for(user_id: int, rows: list[dict], synced_at: str, source: str = "sync") -> int:
    with get_db() as session:
        session.query(FinanceTransactionEntity).filter_by(user_id=user_id).delete()
        if rows:
            session.bulk_insert_mappings(FinanceTransactionEntity, [_values(user_id, row, synced_at, source) for row in rows])
        session.flush()
        return len(rows)


def list_for(user_id: int, symbol: Optional[str] = None, limit: int = 500) -> list[FinanceTransaction]:
    with get_db() as session:
        query = session.query(FinanceTransactionEntity).filter_by(user_id=user_id)
        if symbol:
            query = query.filter_by(symbol=symbol)
        rows = query.order_by(FinanceTransactionEntity.transaction_date.desc(), FinanceTransactionEntity.id.desc()).limit(limit).all()
        return [_entity_to_dto(row) for row in rows]


def list_between(user_id: int, start_date: date | None = None, end_date: date | None = None) -> list[FinanceTransaction]:
    with get_db() as session:
        query = session.query(FinanceTransactionEntity).filter_by(user_id=user_id)
        if start_date is not None:
            query = query.filter(FinanceTransactionEntity.transaction_date >= start_date)
        if end_date is not None:
            query = query.filter(FinanceTransactionEntity.transaction_date < end_date)
        rows = query.order_by(FinanceTransactionEntity.transaction_date.asc(), FinanceTransactionEntity.id.asc()).all()
        return [_entity_to_dto(row) for row in rows]


def latest_synced_at(user_id: int) -> str:
    with get_db() as session:
        row = session.query(FinanceTransactionEntity.synced_at).filter_by(user_id=user_id).order_by(FinanceTransactionEntity.synced_at.desc()).first()
        return row[0] if row else ""
