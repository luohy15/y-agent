from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class TgTopicEntity(Base, BaseEntity):
    __tablename__ = "tg_topic"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    group_id = Column(BigInteger, nullable=False)
    topic_id = Column(BigInteger, nullable=True)
    topic_name = Column(String, nullable=False)
    topic_icon = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "group_id", "topic_name"),
    )
