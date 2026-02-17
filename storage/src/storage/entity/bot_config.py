from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, JSON
from .base import Base, BaseEntity


class BotConfigEntity(Base, BaseEntity):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False, default="https://openrouter.ai/api/v1")
    api_key = Column(String, nullable=False, default="")
    api_type = Column(String, nullable=True)
    model = Column(String, nullable=False, default="")
    description = Column(Text, nullable=True)
    openrouter_config = Column(JSON, nullable=True)
    prompts = Column(JSON, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    custom_api_path = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
    )
