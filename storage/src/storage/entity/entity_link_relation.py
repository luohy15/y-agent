from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class EntityLinkRelationEntity(Base, BaseEntity):
    __tablename__ = "entity_link_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    activity_id = Column(String, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", "activity_id"),
    )
