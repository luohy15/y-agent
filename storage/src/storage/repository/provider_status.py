"""Transactional persistence for normalized provider status data."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.provider_status import (
    ProviderStatusComponentEntity,
    ProviderStatusComponentTransitionEntity,
    ProviderStatusEventEntity,
    ProviderStatusIncidentEntity,
    ProviderStatusIncidentUpdateEntity,
    ProviderStatusSourceEntity,
)


def ingest(values: dict) -> bool:
    """Persist one validated envelope. Concurrent duplicate receipts return False."""
    with get_db() as session:
        return _ingest(session, values)


def ingest_batch(values: list[dict]) -> int:
    """Persist a fully validated reconciliation snapshot in one transaction."""
    with get_db() as session:
        return sum(_ingest(session, item) for item in values)


def _ingest(session, values: dict) -> bool:
    event = values["event"]
    if not _insert_event(session, event):
        _upsert_source(_source(session, values["source"]), values["source"])
        return False
    _upsert_source(_source(session, values["source"]), values["source"])
    for component in values.get("components", ()):
        _upsert_newer(session, ProviderStatusComponentEntity, component)
    for transition in values.get("transitions", ()):
        _insert_transition(session, transition)
    for incident in values.get("incidents", ()):
        _upsert_newer(session, ProviderStatusIncidentEntity, incident)
    for update in values.get("updates", ()):
        _upsert_incident_update(session, update)
    return True


def _insert_event(session, values: dict) -> bool:
    """Use PostgreSQL ON CONFLICT for production and a safe SQLite equivalent locally."""
    table = ProviderStatusEventEntity.__table__
    if session.bind.dialect.name == "postgresql":
        statement = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=("provider", "event_key")
        )
        return session.execute(statement).rowcount == 1
    try:
        with session.begin_nested():
            session.add(ProviderStatusEventEntity(**values))
            session.flush()
        return True
    except IntegrityError:
        return False


def _source(session, values: dict) -> ProviderStatusSourceEntity:
    row = session.query(ProviderStatusSourceEntity).filter_by(provider=values["provider"]).first()
    if row is None:
        row = ProviderStatusSourceEntity(
            provider=values["provider"], page_id=values["page_id"], page_url=values["page_url"]
        )
        session.add(row)
        session.flush()
    return row


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _upsert_source(row, values: dict) -> None:
    row.page_id = values["page_id"]
    row.page_url = values["page_url"]
    row_updated = _as_utc(row.source_updated_at)
    if values.get("source_updated_at") is not None and (
        row_updated is None or values["source_updated_at"] >= row_updated
    ):
        row.indicator = values.get("indicator")
        row.description = values.get("description")
        row.source_updated_at = values["source_updated_at"]
    for field in ("last_webhook_receipt_at", "last_reconciled_at", "last_success_at"):
        value = values.get(field)
        previous = _as_utc(getattr(row, field))
        if value is not None and (previous is None or value > previous):
            setattr(row, field, value)


def _upsert_newer(session, entity, values: dict) -> None:
    row = session.query(entity).filter_by(
        provider=values["provider"], source_id=values["source_id"]
    ).first()
    if row is None:
        session.add(entity(**values))
        return
    if values["source_updated_at"] > _as_utc(row.source_updated_at):
        for key, value in values.items():
            if key not in {"provider", "source_id"}:
                setattr(row, key, value)


def _upsert_incident_update(session, values: dict) -> None:
    row = session.query(ProviderStatusIncidentUpdateEntity).filter_by(
        provider=values["provider"], source_id=values["source_id"]
    ).first()
    if row is None:
        session.add(ProviderStatusIncidentUpdateEntity(**values))
        return
    if values["source_updated_at"] > _as_utc(row.source_updated_at):
        for key, value in values.items():
            if key not in {"provider", "source_id"}:
                setattr(row, key, value)


def _insert_transition(session, values: dict) -> None:
    table = ProviderStatusComponentTransitionEntity.__table__
    if session.bind.dialect.name == "postgresql":
        statement = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=("provider", "component_source_id", "status", "source_timestamp")
        )
        session.execute(statement)
        return
    try:
        with session.begin_nested():
            session.add(ProviderStatusComponentTransitionEntity(**values))
            session.flush()
    except IntegrityError:
        pass


def overview(provider: str) -> ProviderStatusSourceEntity | None:
    with get_db() as session:
        return session.query(ProviderStatusSourceEntity).filter_by(provider=provider).first()


def list_components(provider: str, limit: int) -> list[ProviderStatusComponentEntity]:
    with get_db() as session:
        return session.query(ProviderStatusComponentEntity).filter_by(provider=provider).order_by(
            ProviderStatusComponentEntity.name.asc()
        ).limit(limit).all()


def list_incidents(provider: str, start: datetime, end: datetime, limit: int) -> list[ProviderStatusIncidentEntity]:
    with get_db() as session:
        return session.query(ProviderStatusIncidentEntity).filter(
            ProviderStatusIncidentEntity.provider == provider,
            ProviderStatusIncidentEntity.source_updated_at >= start,
            ProviderStatusIncidentEntity.source_updated_at < end,
        ).order_by(ProviderStatusIncidentEntity.source_updated_at.desc()).limit(limit).all()


def get_incident(provider: str, source_id: str) -> tuple[ProviderStatusIncidentEntity | None, list[ProviderStatusIncidentUpdateEntity]]:
    with get_db() as session:
        incident = session.query(ProviderStatusIncidentEntity).filter_by(
            provider=provider, source_id=source_id
        ).first()
        updates = session.query(ProviderStatusIncidentUpdateEntity).filter_by(
            provider=provider, incident_source_id=source_id
        ).order_by(ProviderStatusIncidentUpdateEntity.source_updated_at.asc()).limit(200).all()
        return incident, updates


def list_component_transitions(provider: str, start: datetime, end: datetime, limit: int) -> list[ProviderStatusComponentTransitionEntity]:
    with get_db() as session:
        return session.query(ProviderStatusComponentTransitionEntity).filter(
            ProviderStatusComponentTransitionEntity.provider == provider,
            ProviderStatusComponentTransitionEntity.source_timestamp >= start,
            ProviderStatusComponentTransitionEntity.source_timestamp < end,
        ).order_by(ProviderStatusComponentTransitionEntity.source_timestamp.asc()).limit(limit).all()


def retention(raw_expires_before: datetime, before_normalized: datetime, batch_size: int) -> dict[str, int]:
    """Delete at most one bounded batch per table; current component state is retained."""
    with get_db() as session:
        result = {}
        for label, entity, column, before in (
            ("events", ProviderStatusEventEntity, ProviderStatusEventEntity.expires_at, raw_expires_before),
            ("transitions", ProviderStatusComponentTransitionEntity, ProviderStatusComponentTransitionEntity.source_timestamp, before_normalized),
            ("updates", ProviderStatusIncidentUpdateEntity, ProviderStatusIncidentUpdateEntity.source_updated_at, before_normalized),
            ("incidents", ProviderStatusIncidentEntity, ProviderStatusIncidentEntity.source_updated_at, before_normalized),
        ):
            ids = [item[0] for item in session.query(entity.id).filter(column < before).order_by(entity.id).limit(batch_size).all()]
            result[label] = session.query(entity).filter(entity.id.in_(ids)).delete(synchronize_session=False) if ids else 0
        return result
