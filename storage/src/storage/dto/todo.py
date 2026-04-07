from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class TodoHistoryEntry:
    timestamp: str
    unix_timestamp: int
    action: str
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'TodoHistoryEntry':
        unix_timestamp = data.get('unix_timestamp')
        if unix_timestamp is None:
            dt = datetime.strptime(data['timestamp'].split('+')[0], "%Y-%m-%dT%H:%M:%S")
            unix_timestamp = int(dt.timestamp() * 1000)
        else:
            unix_timestamp = int(unix_timestamp)
        return cls(
            timestamp=data['timestamp'],
            unix_timestamp=unix_timestamp,
            action=data['action'],
            note=data.get('note'),
        )

    def to_dict(self) -> Dict:
        result = {'timestamp': self.timestamp, 'unix_timestamp': self.unix_timestamp, 'action': self.action}
        if self.note is not None:
            result['note'] = self.note
        return result

@dataclass
class Todo:
    todo_id: str
    name: str
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    pinned: bool = False
    status: str = "pending"
    progress: Optional[str] = None
    completed_at: Optional[str] = None
    history: Optional[List[TodoHistoryEntry]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Todo':
        history = data.get('history')
        if history:
            history = [TodoHistoryEntry.from_dict(h) if isinstance(h, dict) else h for h in history]
        return cls(
            todo_id=data['todo_id'],
            name=data['name'],
            desc=data.get('desc'),
            tags=data.get('tags'),
            due_date=data.get('due_date'),
            priority=data.get('priority'),
            pinned=data.get('pinned', False),
            status=data.get('status', 'pending'),
            progress=data.get('progress'),
            completed_at=data.get('completed_at'),
            history=history,
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'todo_id': self.todo_id,
            'name': self.name,
            'pinned': self.pinned,
            'status': self.status,
        }
        if self.desc is not None:
            result['desc'] = self.desc
        if self.tags is not None:
            result['tags'] = self.tags
        if self.due_date is not None:
            result['due_date'] = self.due_date
        if self.priority is not None:
            result['priority'] = self.priority
        if self.progress is not None:
            result['progress'] = self.progress
        if self.completed_at is not None:
            result['completed_at'] = self.completed_at
        if self.history:
            result['history'] = [h.to_dict() for h in self.history]
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
