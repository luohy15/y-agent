"""Function-based finance transaction repository."""

from typing import Optional

from storage.database.base import get_db
from storage.dto.finance_transaction import FinanceTransaction
from storage.entity.finance_transaction import FinanceTransactionEntity
from storage.util import get_utc_iso8601_timestamp


def _entity_to_dto(entity: FinanceTransactionEntity) -> FinanceTransaction:
    return FinanceTransaction(
        id=entity.id,
        user_id=entity.user_id,
        vm_name=entity.vm_name,
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


def _values(user_id: int, vm_name: str, row: dict, synced_at: str, source: str) -> dict:
    return dict(
        user_id=user_id,
        vm_name=vm_name or "",
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


def replace_for(user_id: int, vm_name: str, rows: list[dict], synced_at: str, source: str = "sync") -> int:
    effective_vm_name = vm_name or ""
    with get_db() as session:
        session.query(FinanceTransactionEntity).filter_by(user_id=user_id, vm_name=effective_vm_name).delete()
        if rows:
            session.bulk_insert_mappings(FinanceTransactionEntity, [_values(user_id, effective_vm_name, row, synced_at, source) for row in rows])
        session.flush()
        return len(rows)


def list_for(user_id: int, vm_name: str, symbol: Optional[str] = None, limit: int = 500) -> list[FinanceTransaction]:
    with get_db() as session:
        query = session.query(FinanceTransactionEntity).filter_by(user_id=user_id, vm_name=vm_name or "")
        if symbol:
            query = query.filter_by(symbol=symbol)
        rows = query.order_by(FinanceTransactionEntity.transaction_date.desc(), FinanceTransactionEntity.id.desc()).limit(limit).all()
        return [_entity_to_dto(row) for row in rows]
