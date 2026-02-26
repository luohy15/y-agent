from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
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
    json_content = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id"),
    )
