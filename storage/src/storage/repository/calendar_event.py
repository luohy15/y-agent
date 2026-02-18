"""Function-based calendar event repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.calendar_event import CalendarEventEntity
from storage.entity.dto import CalendarEvent
from storage.database.base import get_db


def _entity_to_dto(entity: CalendarEventEntity) -> CalendarEvent:
    return CalendarEvent(
        event_id=entity.event_id,
        source_id=entity.source_id,
        summary=entity.summary,
        description=entity.description,
        start_time=entity.start_time,
        end_time=entity.end_time,
        all_day=entity.all_day,
        status=entity.status,
        source=entity.source,
        todo_id=entity.todo_id,
        deleted_at=entity.deleted_at,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_events(
    user_id: int,
    date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    todo_id: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 50,
) -> List[CalendarEvent]:
    with get_db() as session:
        query = session.query(CalendarEventEntity).filter_by(user_id=user_id)
        if not include_deleted:
            query = query.filter(CalendarEventEntity.deleted_at.is_(None))
        if date:
            # Match events whose start_time begins with the date string (YYYY-MM-DD)
            query = query.filter(CalendarEventEntity.start_time.like(f"{date}%"))
        if start:
            query = query.filter(CalendarEventEntity.start_time >= start)
        if end:
            query = query.filter(CalendarEventEntity.start_time <= end)
        if source:
            query = query.filter_by(source=source)
        if todo_id is not None:
            query = query.filter_by(todo_id=todo_id)
        query = query.order_by(CalendarEventEntity.start_time.asc())
        query = query.limit(limit)
        return [_entity_to_dto(row) for row in query.all()]


def get_event(user_id: int, event_id: str, include_deleted: bool = False) -> Optional[CalendarEvent]:
    with get_db() as session:
        query = session.query(CalendarEventEntity).filter_by(user_id=user_id, event_id=event_id)
        if not include_deleted:
            query = query.filter(CalendarEventEntity.deleted_at.is_(None))
        row = query.first()
        return _entity_to_dto(row) if row else None


def save_event(user_id: int, event: CalendarEvent) -> CalendarEvent:
    with get_db() as session:
        entity = session.query(CalendarEventEntity).filter_by(user_id=user_id, event_id=event.event_id).first()
        fields = dict(
            source_id=event.source_id,
            summary=event.summary,
            description=event.description,
            start_time=event.start_time,
            end_time=event.end_time,
            all_day=event.all_day,
            status=event.status,
            source=event.source,
            todo_id=event.todo_id,
            deleted_at=event.deleted_at,
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = CalendarEventEntity(user_id=user_id, event_id=event.event_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def list_deleted_events(user_id: int, limit: int = 50) -> List[CalendarEvent]:
    with get_db() as session:
        query = (
            session.query(CalendarEventEntity)
            .filter_by(user_id=user_id)
            .filter(CalendarEventEntity.deleted_at.isnot(None))
            .order_by(CalendarEventEntity.deleted_at.desc())
            .limit(limit)
        )
        return [_entity_to_dto(row) for row in query.all()]
