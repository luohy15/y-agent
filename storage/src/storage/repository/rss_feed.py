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
        scrape_failure_count=entity.scrape_failure_count or 0,
        scrape_last_run_at=entity.scrape_last_run_at,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_feeds(user_id: int) -> List[RssFeed]:
    with get_db() as session:
        rows = (
            session.query(RssFeedEntity)
            .filter_by(user_id=user_id)
            .order_by(RssFeedEntity.id.asc())
            .all()
        )
        return [_entity_to_dto(row) for row in rows]


def list_all_feeds() -> List[tuple]:
    """Return (user_id, RssFeed) tuples across all users. For scheduled fetcher."""
    with get_db() as session:
        rows = session.query(RssFeedEntity).all()
        return [(row.user_id, _entity_to_dto(row)) for row in rows]


def get_feed(user_id: int, rss_feed_id: str) -> Optional[RssFeed]:
    with get_db() as session:
        row = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        ).first()
        if not row:
            return None
        return _entity_to_dto(row)


def get_feed_by_url(user_id: int, url: str) -> Optional[RssFeed]:
    with get_db() as session:
        row = session.query(RssFeedEntity).filter_by(user_id=user_id, url=url).first()
        if not row:
            return None
        return _entity_to_dto(row)


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


def record_scrape_success(rss_feed_id: str) -> Optional[RssFeed]:
    """Reset scrape_failure_count=0, set scrape_last_run_at=now."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        entity.scrape_failure_count = 0
        entity.scrape_last_run_at = datetime.now(timezone.utc).isoformat()
        session.flush()
        return _entity_to_dto(entity)


def record_scrape_failure(rss_feed_id: str) -> Optional[RssFeed]:
    """Increment scrape_failure_count and update scrape_last_run_at=now."""
    with get_db() as session:
        entity = session.query(RssFeedEntity).filter_by(rss_feed_id=rss_feed_id).first()
        if not entity:
            return None
        entity.scrape_failure_count = (entity.scrape_failure_count or 0) + 1
        entity.scrape_last_run_at = datetime.now(timezone.utc).isoformat()
        session.flush()
        return _entity_to_dto(entity)


def delete_feed(user_id: int, rss_feed_id: str) -> bool:
    with get_db() as session:
        count = session.query(RssFeedEntity).filter_by(
            user_id=user_id, rss_feed_id=rss_feed_id,
        ).delete()
        session.flush()
        return count > 0
