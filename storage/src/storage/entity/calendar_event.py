from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, text, SmallInteger
from .base import Base, BaseEntity


class CalendarEventEntity(Base, BaseEntity):
    __tablename__ = "calendar_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    summary = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="UTC", server_default=text("'UTC'"))
    all_day = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="CONFIRMED")
    source = Column(String, nullable=True)
    todo_id = Column(String, nullable=True)
    deleted_at = Column(String, nullable=True)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "event_id"),
    )
