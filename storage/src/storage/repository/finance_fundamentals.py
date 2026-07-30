"""Function-based finance fundamentals repository."""

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.entity.finance_fundamentals import FinanceFundamentalsEntity
from storage.util import get_utc_iso8601_timestamp


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _entity_to_dict(entity: FinanceFundamentalsEntity) -> dict:
    fetched_at = entity.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return {
        "symbol": entity.symbol,
        "overview": entity.overview,
        "balance_sheet": entity.balance_sheet,
        "income_statement": entity.income_statement,
        "cash_flow": entity.cash_flow,
        "earnings": entity.earnings,
        "fetched_at": fetched_at,
    }


def get(symbol: str) -> dict | None:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return None
    with get_db() as session:
        row = session.query(FinanceFundamentalsEntity).filter(FinanceFundamentalsEntity.symbol == normalized).one_or_none()
        return _entity_to_dict(row) if row else None


def upsert(row: dict) -> dict:
    symbol = _normalize_symbol(row.get("symbol") or "")
    if not symbol:
        raise ValueError("symbol is required")
    values = {
        "symbol": symbol,
        "overview": row.get("overview"),
        "balance_sheet": row.get("balance_sheet"),
        "income_statement": row.get("income_statement"),
        "cash_flow": row.get("cash_flow"),
        "earnings": row.get("earnings"),
        "fetched_at": _parse_datetime(row["fetched_at"]),
        "updated_at": get_utc_iso8601_timestamp(),
    }
    with get_db() as session:
        stmt = insert(FinanceFundamentalsEntity).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FinanceFundamentalsEntity.symbol],
            set_={
                "overview": stmt.excluded.overview,
                "balance_sheet": stmt.excluded.balance_sheet,
                "income_statement": stmt.excluded.income_statement,
                "cash_flow": stmt.excluded.cash_flow,
                "earnings": stmt.excluded.earnings,
                "fetched_at": stmt.excluded.fetched_at,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)
        session.flush()
        entity = session.query(FinanceFundamentalsEntity).filter(FinanceFundamentalsEntity.symbol == symbol).one()
        return _entity_to_dict(entity)
