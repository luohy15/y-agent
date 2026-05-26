"""Function-based finance realtime quote repository."""

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.entity.finance_realtime_quote import FinanceRealtimeQuoteEntity
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


def _entity_to_dict(entity: FinanceRealtimeQuoteEntity) -> dict:
    as_of = entity.as_of
    fetched_at = entity.fetched_at
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return {
        "symbol": entity.symbol,
        "as_of": as_of,
        "close": entity.close,
        "fetched_at": fetched_at,
    }


def _values(row: dict) -> dict:
    return {
        "symbol": _normalize_symbol(row.get("symbol") or row.get("ticker") or ""),
        "as_of": _parse_datetime(row["as_of"]),
        "close": float(row.get("close") if row.get("close") is not None else row.get("price")),
        "fetched_at": _parse_datetime(row["fetched_at"]),
        "updated_at": get_utc_iso8601_timestamp(),
    }


def get_many(symbols: list[str]) -> dict[str, dict]:
    normalized = sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)})
    if not normalized:
        return {}
    with get_db() as session:
        rows = session.query(FinanceRealtimeQuoteEntity).filter(FinanceRealtimeQuoteEntity.symbol.in_(normalized)).all()
        return {row.symbol: _entity_to_dict(row) for row in rows}


def upsert_many(rows: list[dict]) -> int:
    normalized_rows = [_values(row) for row in rows]
    normalized_rows = [row for row in normalized_rows if row["symbol"]]
    if not normalized_rows:
        return 0
    with get_db() as session:
        for row in normalized_rows:
            stmt = insert(FinanceRealtimeQuoteEntity).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=[FinanceRealtimeQuoteEntity.symbol],
                set_={
                    "as_of": stmt.excluded.as_of,
                    "close": stmt.excluded.close,
                    "fetched_at": stmt.excluded.fetched_at,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            session.execute(stmt)
        session.flush()
        return len(normalized_rows)
