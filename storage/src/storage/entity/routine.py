from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, text
from .base import Base, BaseEntity


class RoutineEntity(Base, BaseEntity):
    __tablename__ = "routine"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    routine_id = Column(String, nullable=False)

    # identity
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # schedule (cron expression, evaluated in Y_AGENT_TIMEZONE)
    schedule = Column(String, nullable=False)

    # action — structured chat dispatch only (v1)
    target_topic = Column(String, nullable=True)
    target_skill = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    work_dir = Column(String, nullable=True)
    backend = Column(String, nullable=True)

    # state
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    last_run_at = Column(String, nullable=True)
    last_run_status = Column(String, nullable=True)
    last_chat_id = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "routine_id"),
    )
