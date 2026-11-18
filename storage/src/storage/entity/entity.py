from sqlalchemy import Column, Integer, String, JSON, ForeignKey, UniqueConstraint, SmallInteger
from .base import Base, BaseEntity


class EntityEntity(Base, BaseEntity):
    __tablename__ = "entity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    entity_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    front_matter = Column(JSON, nullable=True)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_id"),
    )
