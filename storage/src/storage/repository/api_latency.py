"""Persistence primitives for API latency capture, rollup, and queries."""

from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_

from storage.database.base import get_db
from storage.entity.api_latency_event import ApiLatencyEventEntity
from storage.entity.api_latency_rollup import ApiLatencyRollupEntity


ROLLUP_KEY = (
    "grain",
    "bucket_start",
    "method",
    "route",
    "status_class",
    "completion",
    "module_slug",
)


def raw_hour_counts(start: datetime, end: datetime) -> list[tuple[datetime, int]]:
    """Indexed retained-window source counts, one row per UTC started hour."""
    with get_db() as session:
        hour = func.date_trunc("hour", ApiLatencyEventEntity.started_at)
        return [
            (row[0], int(row[1]))
            for row in (
                session.query(hour, func.count(ApiLatencyEventEntity.id))
                .filter(
                    ApiLatencyEventEntity.started_at >= start,
                    ApiLatencyEventEntity.started_at < end,
                )
                .group_by(hour)
                .order_by(hour)
                .all()
            )
        ]


def rollup_hour_counts(start: datetime, end: datetime) -> list[tuple[datetime, int]]:
    with get_db() as session:
        return [
            (row[0], int(row[1] or 0))
            for row in (
                session.query(
                    ApiLatencyRollupEntity.bucket_start,
                    func.sum(ApiLatencyRollupEntity.request_count),
                )
                .filter(
                    ApiLatencyRollupEntity.grain == "hour",
                    ApiLatencyRollupEntity.bucket_start >= start,
                    ApiLatencyRollupEntity.bucket_start < end,
                )
                .group_by(ApiLatencyRollupEntity.bucket_start)
                .order_by(ApiLatencyRollupEntity.bucket_start)
                .all()
            )
        ]


def create_event(values: dict) -> None:
    with get_db() as session:
        session.add(ApiLatencyEventEntity(**values))


def _event_query(session, start: datetime, end: datetime, route: str | None, filters: dict):
    query = session.query(ApiLatencyEventEntity).filter(
        ApiLatencyEventEntity.started_at >= start,
        ApiLatencyEventEntity.started_at < end,
    )
    if route is not None:
        query = query.filter(ApiLatencyEventEntity.route == route)
    for field, value in filters.items():
        query = query.filter(getattr(ApiLatencyEventEntity, field) == value)
    return query


def list_events(start: datetime, end: datetime) -> list[ApiLatencyEventEntity]:
    with get_db() as session:
        return _event_query(session, start, end, None, {}).order_by(
            ApiLatencyEventEntity.started_at.asc()
        ).all()


def query_events(
    start: datetime,
    end: datetime,
    *,
    route: str | None,
    filters: dict,
    order: str,
    limit: int,
) -> list[ApiLatencyEventEntity]:
    with get_db() as session:
        query = _event_query(session, start, end, route, filters)
        order_column = (
            ApiLatencyEventEntity.started_at
            if order == "recent"
            else ApiLatencyEventEntity.duration_ms
        )
        return query.order_by(order_column.desc(), ApiLatencyEventEntity.id.desc()).limit(limit).all()


def list_rollups(grain: str, start: datetime, end: datetime) -> list[ApiLatencyRollupEntity]:
    with get_db() as session:
        return (
            session.query(ApiLatencyRollupEntity)
            .filter(
                ApiLatencyRollupEntity.grain == grain,
                ApiLatencyRollupEntity.bucket_start >= start,
                ApiLatencyRollupEntity.bucket_start < end,
            )
            .order_by(ApiLatencyRollupEntity.bucket_start.asc())
            .all()
        )


def list_daily_source(start: datetime, end: datetime) -> list[ApiLatencyRollupEntity]:
    """Use daily buckets, except current UTC day which comes from hourly rows."""
    with get_db() as session:
        current_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
        current_hour_end = end.replace(minute=0, second=0, microsecond=0)
        if current_hour_end < end:
            current_hour_end += timedelta(hours=1)
        return (
            session.query(ApiLatencyRollupEntity)
            .filter(
                ApiLatencyRollupEntity.bucket_start >= start,
                ApiLatencyRollupEntity.bucket_start < current_hour_end,
                or_(
                    and_(
                        ApiLatencyRollupEntity.grain == "day",
                        ApiLatencyRollupEntity.bucket_start < current_day,
                    ),
                    and_(
                        ApiLatencyRollupEntity.grain == "hour",
                        ApiLatencyRollupEntity.bucket_start >= current_day,
                    ),
                ),
            )
            .order_by(ApiLatencyRollupEntity.bucket_start.asc())
            .all()
        )


def replace_rollup_window(grain: str, start: datetime, end: datetime, rows: list[dict]) -> int:
    """Replace a recomputed grain window atomically, including now-empty keys."""
    with get_db() as session:
        session.execute(
            delete(ApiLatencyRollupEntity).where(
                ApiLatencyRollupEntity.grain == grain,
                ApiLatencyRollupEntity.bucket_start >= start,
                ApiLatencyRollupEntity.bucket_start < end,
            )
        )
        if rows:
            session.execute(ApiLatencyRollupEntity.__table__.insert(), rows)
        return len(rows)


def delete_event_batch(before: datetime, limit: int) -> int:
    with get_db() as session:
        ids = [
            row[0]
            for row in (
                session.query(ApiLatencyEventEntity.id)
                .filter(ApiLatencyEventEntity.started_at < before)
                .order_by(ApiLatencyEventEntity.started_at.asc())
                .limit(limit)
                .all()
            )
        ]
        if ids:
            session.query(ApiLatencyEventEntity).filter(ApiLatencyEventEntity.id.in_(ids)).delete(
                synchronize_session=False
            )
        return len(ids)


def delete_rollup_batch(grain: str, before: datetime, limit: int) -> int:
    with get_db() as session:
        ids = [
            row[0]
            for row in (
                session.query(ApiLatencyRollupEntity.id)
                .filter(
                    ApiLatencyRollupEntity.grain == grain,
                    ApiLatencyRollupEntity.bucket_start < before,
                )
                .order_by(ApiLatencyRollupEntity.bucket_start.asc())
                .limit(limit)
                .all()
            )
        ]
        if ids:
            session.query(ApiLatencyRollupEntity).filter(ApiLatencyRollupEntity.id.in_(ids)).delete(
                synchronize_session=False
            )
        return len(ids)


def storage_meta() -> dict:
    with get_db() as session:
        event_min = session.query(func.min(ApiLatencyEventEntity.started_at)).scalar()
        rollup_min = session.query(func.min(ApiLatencyRollupEntity.bucket_start)).scalar()
        last_rollup = session.query(func.max(ApiLatencyRollupEntity.bucket_start)).scalar()
        event_routes = session.query(ApiLatencyEventEntity.route).distinct()
        rollup_routes = session.query(ApiLatencyRollupEntity.route).distinct()
        distinct_route_count = event_routes.union(rollup_routes).count()
        return {
            "event_count": session.query(ApiLatencyEventEntity).count(),
            "hourly_count": session.query(ApiLatencyRollupEntity).filter_by(grain="hour").count(),
            "daily_count": session.query(ApiLatencyRollupEntity).filter_by(grain="day").count(),
            "distinct_route_count": distinct_route_count,
            "event_min": event_min,
            "rollup_min": rollup_min,
            "last_rollup": last_rollup,
        }
