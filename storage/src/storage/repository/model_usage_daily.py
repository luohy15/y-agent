"""Function-based model_usage_daily repository (idempotent daily upsert)."""

from datetime import date
from typing import Optional

from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.dto.model_usage_daily import ModelUsageDaily
from storage.entity.model_usage_daily import ModelUsageDailyEntity
from storage.util import get_utc_iso8601_timestamp


def _entity_to_dto(entity: ModelUsageDailyEntity) -> ModelUsageDaily:
    return ModelUsageDaily(
        id=entity.id,
        user_id=entity.user_id,
        usage_date=str(entity.usage_date),
        source=entity.source,
        provider=entity.provider,
        model=entity.model,
        scope=entity.scope,
        scope_id=entity.scope_id,
        scope_name=entity.scope_name,
        input_tokens=entity.input_tokens,
        output_tokens=entity.output_tokens,
        cache_create_tokens=entity.cache_create_tokens,
        cache_read_tokens=entity.cache_read_tokens,
        all_tokens=entity.all_tokens,
        requests=entity.requests,
        cost=entity.cost,
        cost_basis=entity.cost_basis,
        synced_at=entity.synced_at,
    )


def _values(user_id: int, row: dict, synced_at: str) -> dict:
    return dict(
        user_id=user_id,
        usage_date=row.get("usage_date") or row.get("date"),
        source=row["source"],
        provider=row.get("provider") or "",
        model=row.get("model") or "*",
        scope=row.get("scope") or "aggregate",
        scope_id=row.get("scope_id") or "",
        scope_name=row.get("scope_name") or "",
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        cache_create_tokens=int(row.get("cache_create_tokens") or 0),
        cache_read_tokens=int(row.get("cache_read_tokens") or 0),
        all_tokens=int(row.get("all_tokens") or 0),
        requests=int(row.get("requests") or 0),
        cost=float(row.get("cost") or 0.0),
        cost_basis=row.get("cost_basis") or "real",
        synced_at=synced_at,
        updated_at=get_utc_iso8601_timestamp(),
    )


def upsert_daily(user_id: int, rows: list[dict], synced_at: str) -> int:
    """Upsert usage rows on (user, date, source, scope_id, model). Re-pulling
    the still-mutating current day overwrites; a finalized past day is a no-op."""
    with get_db() as session:
        for row in rows:
            stmt = insert(ModelUsageDailyEntity).values(**_values(user_id, row, synced_at))
            stmt = stmt.on_conflict_do_update(
                constraint="uq_model_usage_daily",
                set_={
                    "provider": stmt.excluded.provider,
                    "scope": stmt.excluded.scope,
                    "scope_name": stmt.excluded.scope_name,
                    "input_tokens": stmt.excluded.input_tokens,
                    "output_tokens": stmt.excluded.output_tokens,
                    "cache_create_tokens": stmt.excluded.cache_create_tokens,
                    "cache_read_tokens": stmt.excluded.cache_read_tokens,
                    "all_tokens": stmt.excluded.all_tokens,
                    "requests": stmt.excluded.requests,
                    "cost": stmt.excluded.cost,
                    "cost_basis": stmt.excluded.cost_basis,
                    "synced_at": stmt.excluded.synced_at,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            session.execute(stmt)
        session.flush()
        return len(rows)


def list_for(
    user_id: int,
    source: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 1000,
) -> list[ModelUsageDaily]:
    parsed_from = date.fromisoformat(from_date) if from_date else None
    parsed_to = date.fromisoformat(to_date) if to_date else None
    with get_db() as session:
        query = session.query(ModelUsageDailyEntity).filter_by(user_id=user_id)
        if source:
            query = query.filter_by(source=source)
        if parsed_from:
            query = query.filter(ModelUsageDailyEntity.usage_date >= parsed_from)
        if parsed_to:
            query = query.filter(ModelUsageDailyEntity.usage_date <= parsed_to)
        rows = (
            query.order_by(
                ModelUsageDailyEntity.usage_date.desc(),
                ModelUsageDailyEntity.source.asc(),
                ModelUsageDailyEntity.model.asc(),
            )
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(row) for row in rows]
