from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, text
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
    role = Column(String, nullable=True, index=True)
    topic = Column(String, nullable=True, index=True)
    trace_id = Column(String, nullable=True, index=True)
    json_content = Column(Text, nullable=False)
    search_text = Column(Text, nullable=True)  # extracted message text for fast search
    status = Column(String, nullable=False, server_default="idle")
    unread = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id"),
    )
