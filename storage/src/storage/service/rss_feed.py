"""RSS feed service."""

from typing import List, Optional

from storage.dto.rss_feed import RssFeed
from storage.repository import rss_feed as rss_feed_repo


def list_feeds(user_id: int) -> List[RssFeed]:
    return rss_feed_repo.list_feeds(user_id)


def list_all_feeds() -> List[tuple]:
    """List (user_id, feed) tuples across users. For scheduled fetcher."""
    return rss_feed_repo.list_all_feeds()


def get_feed(user_id: int, rss_feed_id: str) -> Optional[RssFeed]:
    return rss_feed_repo.get_feed(user_id, rss_feed_id)


def add_feed(user_id: int, url: str, title: Optional[str] = None) -> RssFeed:
    existing = rss_feed_repo.get_feed_by_url(user_id, url)
    if existing:
        return existing
    return rss_feed_repo.add_feed(user_id, url, title=title)


def update_feed(user_id: int, rss_feed_id: str, title: Optional[str] = None) -> Optional[RssFeed]:
    return rss_feed_repo.update_feed(user_id, rss_feed_id, title=title)


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


def delete_feed(user_id: int, rss_feed_id: str) -> bool:
    return rss_feed_repo.delete_feed(user_id, rss_feed_id)
