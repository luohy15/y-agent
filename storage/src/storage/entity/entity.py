from sqlalchemy import Column, Integer, String, JSON, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class EntityEntity(Base, BaseEntity):
    __tablename__ = "entity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    entity_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    front_matter = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_id"),
    )
