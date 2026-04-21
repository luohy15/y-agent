from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class LinkEntity(Base, BaseEntity):
    __tablename__ = "link"

    id = Column(Integer, primary_key=True, autoincrement=True)
    link_id = Column(String, nullable=False, unique=True)
    base_url = Column(String, nullable=False, unique=True)  # URL without query params
    title = Column(String, nullable=True)
    download_status = Column(String, nullable=True)  # pending/downloading/done/failed
    content_key = Column(String, nullable=True)       # S3 key for stored content
    source = Column(String, nullable=True)            # 'rss' | null (browser/manual)
    source_feed_id = Column(String, nullable=True)    # rss_feed.rss_feed_id (public string, no FK — preserved after feed delete)
    crawl_fail_count = Column(Integer, nullable=True, default=0)  # download failure counter for batch backoff


class LinkActivityEntity(Base, BaseEntity):
    __tablename__ = "link_activity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    activity_id = Column(String, nullable=False)
    link_id = Column(Integer, ForeignKey('link.id', ondelete='CASCADE'), nullable=False, index=True)
    url = Column(String, nullable=False)        # full URL for this visit
    title = Column(String, nullable=True)
    timestamp = Column(BigInteger, nullable=False, index=True)  # unix ms from browser
    download_status = Column(String, nullable=True)  # per-activity download status (for url != base_url)
    content_key = Column(String, nullable=True)       # per-activity S3 key (for url != base_url)

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id"),
        UniqueConstraint("user_id", "timestamp"),
    )
