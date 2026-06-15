from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class ClaudeStatusStateEntity(Base, BaseEntity):
    """Per-user dedup state for Claude status RSS incidents.

    Tracks the latest known status of each incident GUID so the worker step
    only fires one Telegram notification when an incident first appears and
    one more when it resolves.
    """

    __tablename__ = "claude_status_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    incident_guid = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    first_seen_at = Column(String, nullable=False)
    last_updated_at = Column(String, nullable=False)
    notified_at = Column(String, nullable=True)
    resolved_notified_at = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "incident_guid"),
    )
