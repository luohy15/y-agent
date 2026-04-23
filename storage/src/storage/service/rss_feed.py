"""RSS feed service."""

from typing import Any, Dict, List, Optional

from storage.dto.rss_feed import RssFeed
from storage.repository import rss_feed as rss_feed_repo


def list_feeds(user_id: int, include_deleted: bool = False) -> List[RssFeed]:
    return rss_feed_repo.list_feeds(user_id, include_deleted=include_deleted)


def list_all_feeds(include_deleted: bool = False) -> List[tuple]:
    """List (user_id, feed) tuples across users. For scheduled fetcher."""
    return rss_feed_repo.list_all_feeds(include_deleted=include_deleted)


def get_feed(user_id: int, rss_feed_id: str, include_deleted: bool = False) -> Optional[RssFeed]:
    return rss_feed_repo.get_feed(user_id, rss_feed_id, include_deleted=include_deleted)


def add_feed(
    user_id: int,
    url: str,
    title: Optional[str] = None,
    feed_type: Optional[str] = None,
    scrape_config: Optional[Dict[str, Any]] = None,
) -> RssFeed:
    existing = rss_feed_repo.get_feed_by_url(user_id, url, include_deleted=True)
    if existing:
        if existing.deleted_at is not None:
            rss_feed_repo.restore_feed(user_id, existing.rss_feed_id)
            existing.deleted_at = None
        return existing
    return rss_feed_repo.add_feed(
        user_id,
        url,
        title=title,
        feed_type=feed_type,
        scrape_config=scrape_config,
    )


def update_feed(
    user_id: int,
    rss_feed_id: str,
    title: Optional[str] = None,
    feed_type: Optional[str] = None,
    scrape_config: Optional[Dict[str, Any]] = None,
) -> Optional[RssFeed]:
    return rss_feed_repo.update_feed(
        user_id,
        rss_feed_id,
        title=title,
        feed_type=feed_type,
        scrape_config=scrape_config,
    )


def update_fetch_state(
    rss_feed_id: str,
    last_fetched_at: Optional[str] = None,
    last_item_ts: Optional[int] = None,
) -> Optional[RssFeed]:
    return rss_feed_repo.update_fetch_state(
        rss_feed_id,
        last_fetched_at=last_fetched_at,
        last_item_ts=last_item_ts,
    )


def update_last_item_ts(rss_feed_id: str, last_item_ts: int) -> Optional[RssFeed]:
    return rss_feed_repo.update_last_item_ts(rss_feed_id, last_item_ts)


def record_fetch_success(rss_feed_id: str) -> Optional[RssFeed]:
    return rss_feed_repo.record_fetch_success(rss_feed_id)


def record_fetch_failure(rss_feed_id: str) -> Optional[RssFeed]:
    return rss_feed_repo.record_fetch_failure(rss_feed_id)


def delete_feed(user_id: int, rss_feed_id: str) -> bool:
    return rss_feed_repo.delete_feed(user_id, rss_feed_id)


def restore_feed(user_id: int, rss_feed_id: str) -> bool:
    return rss_feed_repo.restore_feed(user_id, rss_feed_id)


def list_deleted_feeds(user_id: int, limit: int = 50) -> List[RssFeed]:
    return rss_feed_repo.list_deleted_feeds(user_id, limit=limit)
