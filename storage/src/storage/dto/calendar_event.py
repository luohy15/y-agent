from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class CalendarEvent:
    event_id: str
    summary: str
    start_time: str
    source_id: Optional[str] = None
    description: Optional[str] = None
    end_time: Optional[str] = None
    all_day: bool = False
    status: str = "CONFIRMED"
    source: Optional[str] = None
    todo_id: Optional[str] = None
    deleted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'CalendarEvent':
        return cls(
            event_id=data['event_id'],
            summary=data['summary'],
            start_time=data['start_time'],
            source_id=data.get('source_id'),
            description=data.get('description'),
            end_time=data.get('end_time'),
            all_day=data.get('all_day', False),
            status=data.get('status', 'CONFIRMED'),
            source=data.get('source'),
            todo_id=data.get('todo_id'),
            deleted_at=data.get('deleted_at'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'event_id': self.event_id,
            'summary': self.summary,
            'start_time': self.start_time,
            'all_day': self.all_day,
            'status': self.status,
        }
        if self.source_id is not None:
            result['source_id'] = self.source_id
        if self.description is not None:
            result['description'] = self.description
        if self.end_time is not None:
            result['end_time'] = self.end_time
        if self.source is not None:
            result['source'] = self.source
        if self.todo_id is not None:
            result['todo_id'] = self.todo_id
        if self.deleted_at is not None:
            result['deleted_at'] = self.deleted_at
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
