from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TgTopic:
    id: Optional[int] = None
    group_id: Optional[int] = None
    topic_id: Optional[int] = None
    topic_name: Optional[str] = None
    topic_icon: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'TgTopic':
        return cls(
            id=data.get('id'),
            group_id=data.get('group_id'),
            topic_id=data.get('topic_id'),
            topic_name=data.get('topic_name'),
            topic_icon=data.get('topic_icon'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {}
        for key in ('id', 'group_id', 'topic_id', 'topic_name', 'topic_icon',
                     'created_at', 'updated_at', 'created_at_unix', 'updated_at_unix'):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result
