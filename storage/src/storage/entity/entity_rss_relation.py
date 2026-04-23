from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class EntityRssRelationEntity(Base, BaseEntity):
    __tablename__ = "entity_rss_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    rss_feed_id = Column(String, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", "rss_feed_id"),
    )
