from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, JSON
from .base import Base, BaseEntity


class ChatEntity(Base, BaseEntity):
    __tablename__ = "chat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    title = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    backend = Column(String, nullable=True)
    origin_chat_id = Column(String, nullable=True, index=True)
    channel_id = Column(String, nullable=True, index=True)
    active_trace_id = Column(String, nullable=True, index=True)
    trace_ids = Column(JSON, nullable=True)  # list of trace_ids this chat participates in
    json_content = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id"),
    )
