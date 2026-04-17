from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class ReminderEntity(Base, BaseEntity):
    __tablename__ = "reminder"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    reminder_id = Column(String, nullable=False)

    # content
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # optional associations
    todo_id = Column(String, nullable=True)
    calendar_event_id = Column(String, nullable=True)

    # scheduling
    remind_at = Column(String, nullable=False)  # ISO 8601 UTC

    # status: pending / sent / cancelled
    status = Column(String, nullable=False, default="pending")
    sent_at = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "reminder_id"),
    )
