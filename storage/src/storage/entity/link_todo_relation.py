from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class LinkTodoRelationEntity(Base, BaseEntity):
    __tablename__ = "link_todo_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    link_id = Column(String, nullable=False, index=True)   # public link_id string
    todo_id = Column(String, nullable=False, index=True)   # public todo_id string

    __table_args__ = (
        UniqueConstraint("user_id", "link_id", "todo_id"),
    )
