from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Reminder:
    reminder_id: str
    title: str
    remind_at: str  # ISO 8601 UTC
    description: Optional[str] = None
    todo_id: Optional[str] = None
    calendar_event_id: Optional[str] = None
    status: str = "pending"
    sent_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Reminder':
        return cls(
            reminder_id=data['reminder_id'],
            title=data['title'],
            remind_at=data['remind_at'],
            description=data.get('description'),
            todo_id=data.get('todo_id'),
            calendar_event_id=data.get('calendar_event_id'),
            status=data.get('status', 'pending'),
            sent_at=data.get('sent_at'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'reminder_id': self.reminder_id,
            'title': self.title,
            'remind_at': self.remind_at,
            'status': self.status,
        }
        if self.description is not None:
            result['description'] = self.description
        if self.todo_id is not None:
            result['todo_id'] = self.todo_id
        if self.calendar_event_id is not None:
            result['calendar_event_id'] = self.calendar_event_id
        if self.sent_at is not None:
            result['sent_at'] = self.sent_at
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
