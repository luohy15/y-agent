from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class NoteTodoRelationEntity(Base, BaseEntity):
    __tablename__ = "note_todo_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    note_id = Column(String, nullable=False, index=True)
    todo_id = Column(String, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "note_id", "todo_id"),
    )
