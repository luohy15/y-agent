from sqlalchemy import Column, Integer, String, Text, BigInteger, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class RssFeedEntity(Base, BaseEntity):
    __tablename__ = "rss_feed"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    rss_feed_id = Column(String, nullable=False, unique=True)
    url = Column(String, nullable=False)
    title = Column(String, nullable=True)
    last_fetched_at = Column(String, nullable=True)
    last_item_ts = Column(BigInteger, nullable=True)
    feed_type = Column(String, nullable=True, default='rss')
    scrape_config = Column(Text, nullable=True)
    fetch_failure_count = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("user_id", "url"),
    )
