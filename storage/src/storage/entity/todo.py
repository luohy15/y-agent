from sqlalchemy import (
    Boolean, CheckConstraint, Column, Integer, String, Text, ForeignKey, UniqueConstraint, JSON,
)
from .base import Base, BaseEntity


class TodoEntity(Base, BaseEntity):
    __tablename__ = "todo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    todo_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    desc = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    due_date = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    awaiting_chat = Column(String, nullable=True)
    machine_wait = Column(JSON, nullable=True)
    progress = Column(Text, nullable=True)
    completed_at = Column(String, nullable=True)
    pinned = Column(Boolean, default=False)
    history = Column(JSON, nullable=False, default=list)
    # Coordinator claim (todo 4080). NULL state means never claimed on this row.
    leader_chat = Column(String, nullable=True)
    leader_claimed_at = Column(String, nullable=True)
    leader_state = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "todo_id"),
        CheckConstraint(
            "leader_state IS NULL"
            " OR (leader_state = 'claimed' AND leader_chat IS NOT NULL)"
            " OR (leader_state = 'released' AND leader_chat IS NULL)",
            name="ck_todo_leader_state",
        ),
    )
