"""Function-based finance transaction repository."""

from datetime import date
from typing import Optional

from sqlalchemy import func

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
    """Return postings for the newest ``limit`` entries (entry-based, not row-based).

    When ``symbol`` is set, only entries that contain at least one matching posting
    are candidates, but every posting of those entries is returned so cash/commission
    legs stay attached.
    """
    with get_db() as session:
        entry_q = session.query(
            FinanceTransactionEntity.entry_id,
            func.max(FinanceTransactionEntity.transaction_date).label("max_date"),
        ).filter(FinanceTransactionEntity.user_id == user_id)

        if symbol:
            matching_entry_ids = (
                session.query(FinanceTransactionEntity.entry_id)
                .filter(
                    FinanceTransactionEntity.user_id == user_id,
                    FinanceTransactionEntity.symbol == symbol,
                )
                .distinct()
            )
            entry_q = entry_q.filter(FinanceTransactionEntity.entry_id.in_(matching_entry_ids))

        entry_rows = (
            entry_q
            .group_by(FinanceTransactionEntity.entry_id)
            .order_by(func.max(FinanceTransactionEntity.transaction_date).desc())
            .limit(limit)
            .all()
        )
        entry_ids = [row.entry_id for row in entry_rows]
        if not entry_ids:
            return []

        rows = (
            session.query(FinanceTransactionEntity)
            .filter(
                FinanceTransactionEntity.user_id == user_id,
                FinanceTransactionEntity.entry_id.in_(entry_ids),
            )
            .order_by(
                FinanceTransactionEntity.transaction_date.desc(),
                FinanceTransactionEntity.id.desc(),
            )
            .all()
        )
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
