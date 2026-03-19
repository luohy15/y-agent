from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, JSON
from .base import Base, BaseEntity


class TraceEntity(Base, BaseEntity):
    __tablename__ = "trace"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    trace_id = Column(String, nullable=False)
    participants = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("user_id", "trace_id"),
    )
