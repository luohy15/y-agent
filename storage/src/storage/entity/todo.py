from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, JSON
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
    progress = Column(Text, nullable=True)
    completed_at = Column(String, nullable=True)
    history = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("user_id", "todo_id"),
    )
