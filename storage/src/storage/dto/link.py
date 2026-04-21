from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class Link:
    link_id: str
    base_url: str
    title: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Link':
        return cls(
            link_id=data['link_id'],
            base_url=data['base_url'],
            title=data.get('title'),
        )

    def to_dict(self) -> Dict:
        result = {
            'link_id': self.link_id,
            'base_url': self.base_url,
        }
        if self.title is not None:
            result['title'] = self.title
        return result

@dataclass
class LinkActivity:
    activity_id: str
    link_id: str
    url: str
    base_url: str
    timestamp: int
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None
    download_status: Optional[str] = None
    content_key: Optional[str] = None
    source: Optional[str] = None
    source_feed_id: Optional[str] = None

    def to_dict(self) -> Dict:
        result = {
            'activity_id': self.activity_id,
            'link_id': self.link_id,
            'url': self.url,
            'base_url': self.base_url,
            'timestamp': self.timestamp,
        }
        if self.title is not None:
            result['title'] = self.title
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        if self.download_status is not None:
            result['download_status'] = self.download_status
        if self.content_key is not None:
            result['content_key'] = self.content_key
        if self.source is not None:
            result['source'] = self.source
        if self.source_feed_id is not None:
            result['source_feed_id'] = self.source_feed_id
        return result

@dataclass
class LinkSummary:
    link_id: str
    base_url: str
    title: Optional[str]
    timestamps: List[int]
    download_status: Optional[str] = None
    content_key: Optional[str] = None

    def to_dict(self) -> Dict:
        result = {
            'link_id': self.link_id,
            'base_url': self.base_url,
            'timestamps': self.timestamps,
        }
        if self.title is not None:
            result['title'] = self.title
        if self.download_status is not None:
            result['download_status'] = self.download_status
        if self.content_key is not None:
            result['content_key'] = self.content_key
        return result
