"""Function-based rss_feed repository using SQLAlchemy sessions."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from storage.entity.rss_feed import RssFeedEntity
from storage.dto.rss_feed import RssFeed
from storage.database.base import get_db
from storage.util import generate_id


def _parse_scrape_config(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _serialize_scrape_config(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _entity_to_dto(entity: RssFeedEntity) -> RssFeed:
    return RssFeed(
        rss_feed_id=entity.rss_feed_id,
        url=entity.url,
        title=entity.title,
        last_fetched_at=entity.last_fetched_at,
        last_item_ts=entity.last_item_ts,
        feed_type=entity.feed_type or 'rss',
        scrape_config=_parse_scrape_config(entity.scrape_config),
        fetch_failure_count=entity.fetch_failure_count or 0,
        deleted_at=entity.deleted_at,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_feeds(user_id: int, include_deleted: bool = False) -> List[RssFeed]:
    with get_db() as session:
        query = session.query(RssFeedEntity).filter_by(user_id=user_id)
        if not include_deleted:
            query = query.filter(RssFeedEntity.deleted_at.is_(None))
        rows = query.order_by(RssFeedEntity.id.asc()).all()
        return [_entity_to_dto(row) for row in rows]


def list_all_feeds(include_deleted: bool = False) -> List[tuple]:
    """Return (user_id, RssFeed) tuples across all users. For scheduled fetcher."""
    with get_db() as session:
        query = session.query(RssFeedEntity)
        if not include_deleted:
            query = query.filter(RssFeedEntity.deleted_at.is_(None))
        rows = query.all()
        return [(row.user_id, _entity_to_dto(row)) for row in rows]


def get_feed(user_id: int, rss_feed_id: str, include_deleted: bool = False) -> Optional[RssFeed]:
    with get_db() as session:
        query = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        )
        if not include_deleted:
            query = query.filter(RssFeedEntity.deleted_at.is_(None))
        row = query.first()
        if not row:
            return None
        return _entity_to_dto(row)


def get_feed_by_url(user_id: int, url: str, include_deleted: bool = False) -> Optional[RssFeed]:
    with get_db() as session:
        query = session.query(RssFeedEntity).filter_by(user_id=user_id, url=url)
        if not include_deleted:
            query = query.filter(RssFeedEntity.deleted_at.is_(None))
        row = query.first()
        if not row:
            return None
        return _entity_to_dto(row)


def list_deleted_feeds(user_id: int, limit: int = 50) -> List[RssFeed]:
    with get_db() as session:
        query = (
            session.query(RssFeedEntity)
            .filter_by(user_id=user_id)
            .filter(RssFeedEntity.deleted_at.isnot(None))
            .order_by(RssFeedEntity.deleted_at.desc())
            .limit(limit)
        )
        return [_entity_to_dto(row) for row in query.all()]


def add_feed(
    user_id: int,
    url: str,
    title: Optional[str] = None,
    feed_type: Optional[str] = None,
    scrape_config: Optional[Dict[str, Any]] = None,
) -> RssFeed:
    with get_db() as session:
        rss_feed_id = generate_id()
        while session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first():
            rss_feed_id = generate_id()
        entity = RssFeedEntity(
            user_id=user_id,
            rss_feed_id=rss_feed_id,
            url=url,
            title=title,
            feed_type=feed_type or 'rss',
            scrape_config=_serialize_scrape_config(scrape_config),
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def update_feed(
    user_id: int,
    rss_feed_id: str,
    title: Optional[str] = None,
    feed_type: Optional[str] = None,
    scrape_config: Optional[Dict[str, Any]] = None,
) -> Optional[RssFeed]:
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        ).first()
        if not entity:
            return None
        if title is not None:
            entity.title = title
        if feed_type is not None:
            entity.feed_type = feed_type
        if scrape_config is not None:
            entity.scrape_config = _serialize_scrape_config(scrape_config)
        session.flush()
        return _entity_to_dto(entity)


def update_fetch_state(
    rss_feed_id: str,
    last_fetched_at: Optional[str] = None,
    last_item_ts: Optional[int] = None,
) -> Optional[RssFeed]:
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        if last_fetched_at is not None:
            entity.last_fetched_at = last_fetched_at
        if last_item_ts is not None:
            entity.last_item_ts = last_item_ts
        session.flush()
        return _entity_to_dto(entity)


def update_last_item_ts(rss_feed_id: str, last_item_ts: int) -> Optional[RssFeed]:
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        entity.last_item_ts = last_item_ts
        session.flush()
        return _entity_to_dto(entity)


def record_fetch_success(rss_feed_id: str) -> Optional[RssFeed]:
    """Reset failure_count=0, set last_fetched_at=now."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        entity.fetch_failure_count = 0
        entity.last_fetched_at = datetime.now(timezone.utc).isoformat()
        session.flush()
        return _entity_to_dto(entity)


def record_fetch_failure(rss_feed_id: str) -> Optional[RssFeed]:
    """Increment fetch_failure_count and update last_fetched_at=now."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        entity.fetch_failure_count = (entity.fetch_failure_count or 0) + 1
        entity.last_fetched_at = datetime.now(timezone.utc).isoformat()
        session.flush()
        return _entity_to_dto(entity)


def delete_feed(user_id: int, rss_feed_id: str) -> bool:
    """Soft-delete: set deleted_at=now. Idempotent; returns False only if not found."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        ).first()
        if not entity:
            return False
        if entity.deleted_at is None:
            entity.deleted_at = datetime.now(timezone.utc).isoformat()
            session.flush()
        return True


def restore_feed(user_id: int, rss_feed_id: str) -> bool:
    """Clear deleted_at. Returns False if not found or not deleted."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        ).first()
        if not entity or entity.deleted_at is None:
            return False
        entity.deleted_at = None
        session.flush()
        return True
