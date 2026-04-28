from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, JSON
from .base import Base, BaseEntity


class UserPreferenceEntity(Base, BaseEntity):
    __tablename__ = "user_preference"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "key"),
    )
