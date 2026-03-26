from sqlalchemy import Column, Integer, String, ForeignKey
from .base import Base, BaseEntity


class TraceShareEntity(Base, BaseEntity):
    __tablename__ = "trace_share"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    share_id = Column(String, nullable=False, unique=True, index=True)
    trace_id = Column(String, nullable=False)
