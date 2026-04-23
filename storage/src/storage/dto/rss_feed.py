from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RssFeed:
    rss_feed_id: str
    url: str
    title: Optional[str] = None
    last_fetched_at: Optional[str] = None
    last_item_ts: Optional[int] = None
    feed_type: Optional[str] = None
    scrape_config: Optional[Dict[str, Any]] = None
    fetch_failure_count: int = 0
    scrape_failure_count: int = 0
    scrape_last_run_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'RssFeed':
        return cls(
            rss_feed_id=data['rss_feed_id'],
            url=data['url'],
            title=data.get('title'),
            last_fetched_at=data.get('last_fetched_at'),
            last_item_ts=data.get('last_item_ts'),
            feed_type=data.get('feed_type'),
            scrape_config=data.get('scrape_config'),
            fetch_failure_count=data.get('fetch_failure_count', 0) or 0,
            scrape_failure_count=data.get('scrape_failure_count', 0) or 0,
            scrape_last_run_at=data.get('scrape_last_run_at'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'rss_feed_id': self.rss_feed_id,
            'url': self.url,
        }
        if self.title is not None:
            result['title'] = self.title
        if self.last_fetched_at is not None:
            result['last_fetched_at'] = self.last_fetched_at
        if self.last_item_ts is not None:
            result['last_item_ts'] = self.last_item_ts
        if self.feed_type is not None:
            result['feed_type'] = self.feed_type
        if self.scrape_config is not None:
            result['scrape_config'] = self.scrape_config
        if self.fetch_failure_count > 0:
            result['fetch_failure_count'] = self.fetch_failure_count
        if self.scrape_failure_count > 0:
            result['scrape_failure_count'] = self.scrape_failure_count
        if self.scrape_last_run_at is not None:
            result['scrape_last_run_at'] = self.scrape_last_run_at
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
