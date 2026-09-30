"""Persistence primitives for API latency capture, rollup, and queries."""

from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, text

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


def _apply_dimension_filters(query, entity, route: str | None, filters: dict | None):
    if route is not None:
        query = query.filter(entity.route == route)
    for field, value in (filters or {}).items():
        query = query.filter(getattr(entity, field) == value)
    return query


def _event_query(session, start: datetime, end: datetime, route: str | None, filters: dict | None):
    query = session.query(ApiLatencyEventEntity).filter(
        ApiLatencyEventEntity.started_at >= start,
        ApiLatencyEventEntity.started_at < end,
    )
    return _apply_dimension_filters(query, ApiLatencyEventEntity, route, filters)


_EVENT_FILTERS = ("method", "status_class", "completion", "module_slug")
_PERCENTILES = (
    "percentile_cont(ARRAY[0.5, 0.95, 0.99]::float8[]) "
    "WITHIN GROUP (ORDER BY duration_ms)"
)


def _raw_where(start: datetime, end: datetime, route: str | None, filters: dict | None):
    unknown = set(filters or {}) - set(_EVENT_FILTERS)
    if unknown:
        raise ValueError("unsupported API latency filter")
    clauses = ["started_at >= :start", "started_at < :end"]
    params = {"start": start, "end": end}
    if route is not None:
        clauses.append("route = :route")
        params["route"] = route
    for field in _EVENT_FILTERS:
        if filters and field in filters:
            clauses.append(f"{field} = :{field}")
            params[field] = filters[field]
    return " AND ".join(clauses), params


def _percentiles(value):
    if not value:
        return None, None, None
    p50, p95, p99 = value
    return float(p50), float(p95), float(p99)


def _count_row(row) -> dict:
    p50, p95, p99 = _percentiles(row.pcts)
    return {
        "request_count": int(row.request_count or 0),
        "error_count": int(row.error_count or 0),
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
    }


def aggregate_raw_summary(
    start: datetime,
    end: datetime,
    *,
    route: str | None = None,
    filters: dict | None = None,
) -> dict:
    """Exact counts and percentiles for one raw window, without loading events.

    One statement returns the whole window and each UTC hour. A row that is
    both 5xx and internal_failure counts as one error.
    """
    where, params = _raw_where(start, end, route, filters)
    statement = text(
        f"""
        SELECT bucket,
               GROUPING(bucket) AS is_total,
               COUNT(*) AS request_count,
               COUNT(*) FILTER (
                   WHERE status_class = '5xx' OR completion = 'internal_failure'
               ) AS error_count,
               {_PERCENTILES} AS pcts
        FROM (
            SELECT (date_trunc('hour', started_at AT TIME ZONE 'UTC')
                    AT TIME ZONE 'UTC') AS bucket,
                   duration_ms, status_class, completion
            FROM {ApiLatencyEventEntity.__tablename__}
            WHERE {where}
        ) AS raw_window
        GROUP BY GROUPING SETS ((), (bucket))
        """
    )
    empty = {
        "request_count": 0,
        "error_count": 0,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
    }
    total = dict(empty)
    series = []
    with get_db() as session:
        for row in session.execute(statement, params):
            item = _count_row(row)
            if int(row.is_total) == 1:
                total = item
            else:
                item["bucket_start"] = row.bucket
                series.append(item)
    series.sort(key=lambda item: item["bucket_start"])
    return {"total": total, "series": series}


def aggregate_raw_routes(
    start: datetime,
    end: datetime,
    *,
    filters: dict | None = None,
) -> list[dict]:
    """One grouped statement per route. Ordering stays in the service."""
    where, params = _raw_where(start, end, None, filters)
    statement = text(
        f"""
        SELECT route,
               COUNT(*) AS request_count,
               COUNT(*) FILTER (
                   WHERE status_class = '5xx' OR completion = 'internal_failure'
               ) AS error_count,
               {_PERCENTILES} AS pcts
        FROM {ApiLatencyEventEntity.__tablename__}
        WHERE {where}
        GROUP BY route
        """
    )
    with get_db() as session:
        return [
            {"route": row.route, **_count_row(row)}
            for row in session.execute(statement, params)
        ]


def list_events(
    start: datetime,
    end: datetime,
    *,
    route: str | None = None,
    filters: dict | None = None,
) -> list[ApiLatencyEventEntity]:
    with get_db() as session:
        return _event_query(session, start, end, route, filters).order_by(
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


def list_rollups(
    grain: str,
    start: datetime,
    end: datetime,
    *,
    route: str | None = None,
    filters: dict | None = None,
) -> list[ApiLatencyRollupEntity]:
    with get_db() as session:
        query = session.query(ApiLatencyRollupEntity).filter(
            ApiLatencyRollupEntity.grain == grain,
            ApiLatencyRollupEntity.bucket_start >= start,
            ApiLatencyRollupEntity.bucket_start < end,
        )
        query = _apply_dimension_filters(query, ApiLatencyRollupEntity, route, filters)
        return query.order_by(ApiLatencyRollupEntity.bucket_start.asc()).all()


def list_daily_source(
    start: datetime,
    end: datetime,
    *,
    route: str | None = None,
    filters: dict | None = None,
) -> list[ApiLatencyRollupEntity]:
    """Use daily buckets, except current UTC day which comes from hourly rows."""
    with get_db() as session:
        current_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
        current_hour_end = end.replace(minute=0, second=0, microsecond=0)
        if current_hour_end < end:
            current_hour_end += timedelta(hours=1)
        query = session.query(ApiLatencyRollupEntity).filter(
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
        query = _apply_dimension_filters(query, ApiLatencyRollupEntity, route, filters)
        return query.order_by(ApiLatencyRollupEntity.bucket_start.asc()).all()


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


def earliest_event_at() -> datetime | None:
    with get_db() as session:
        return session.query(func.min(ApiLatencyEventEntity.started_at)).scalar()


def storage_meta() -> dict:
    with get_db() as session:
        event_min = session.query(func.min(ApiLatencyEventEntity.started_at)).scalar()
        rollup_min = session.query(func.min(ApiLatencyRollupEntity.bucket_start)).scalar()
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
        }
