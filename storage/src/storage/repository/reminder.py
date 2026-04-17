"""Function-based reminder repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.reminder import ReminderEntity
from storage.dto.reminder import Reminder
from storage.database.base import get_db


def _entity_to_dto(entity: ReminderEntity) -> Reminder:
    return Reminder(
        reminder_id=entity.reminder_id,
        title=entity.title,
        description=entity.description,
        todo_id=entity.todo_id,
        calendar_event_id=entity.calendar_event_id,
        remind_at=entity.remind_at,
        status=entity.status,
        sent_at=entity.sent_at,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_reminders(
    user_id: int,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Reminder]:
    with get_db() as session:
        query = session.query(ReminderEntity).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        query = query.order_by(ReminderEntity.remind_at.asc())
        query = query.limit(limit)
        return [_entity_to_dto(row) for row in query.all()]


def get_reminder(user_id: int, reminder_id: str) -> Optional[Reminder]:
    with get_db() as session:
        row = session.query(ReminderEntity).filter_by(user_id=user_id, reminder_id=reminder_id).first()
        return _entity_to_dto(row) if row else None


def save_reminder(user_id: int, reminder: Reminder) -> Reminder:
    with get_db() as session:
        entity = session.query(ReminderEntity).filter_by(user_id=user_id, reminder_id=reminder.reminder_id).first()
        fields = dict(
            title=reminder.title,
            description=reminder.description,
            todo_id=reminder.todo_id,
            calendar_event_id=reminder.calendar_event_id,
            remind_at=reminder.remind_at,
            status=reminder.status,
            sent_at=reminder.sent_at,
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = ReminderEntity(user_id=user_id, reminder_id=reminder.reminder_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def get_pending_reminders(before: str) -> List[dict]:
    """Get all pending reminders with remind_at <= before (UTC ISO 8601).

    Returns list of dicts with reminder DTO and user_id (internal) for the caller
    to resolve telegram info.
    """
    with get_db() as session:
        rows = (
            session.query(ReminderEntity)
            .filter_by(status="pending")
            .filter(ReminderEntity.remind_at <= before)
            .all()
        )
        return [
            {"user_id": row.user_id, "reminder": _entity_to_dto(row)}
            for row in rows
        ]


def mark_sent(user_id: int, reminder_id: str, sent_at: str) -> Optional[Reminder]:
    with get_db() as session:
        entity = session.query(ReminderEntity).filter_by(user_id=user_id, reminder_id=reminder_id).first()
        if not entity:
            return None
        entity.status = "sent"
        entity.sent_at = sent_at
        session.flush()
        return _entity_to_dto(entity)
