from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class DevWorktreeHistoryEntry:
    timestamp: str
    unix_timestamp: int
    action: str
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'DevWorktreeHistoryEntry':
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
class DevWorktree:
    worktree_id: str
    name: str
    project_path: str
    worktree_path: str
    branch: str
    status: str = "active"
    todo_id: Optional[str] = None
    server_state: Optional[Dict] = None
    history: Optional[List[DevWorktreeHistoryEntry]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'DevWorktree':
        history = data.get('history')
        if history:
            history = [DevWorktreeHistoryEntry.from_dict(h) if isinstance(h, dict) else h for h in history]
        return cls(
            worktree_id=data['worktree_id'],
            name=data['name'],
            project_path=data['project_path'],
            worktree_path=data['worktree_path'],
            branch=data['branch'],
            status=data.get('status', 'active'),
            todo_id=data.get('todo_id'),
            server_state=data.get('server_state'),
            history=history,
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'worktree_id': self.worktree_id,
            'name': self.name,
            'project_path': self.project_path,
            'worktree_path': self.worktree_path,
            'branch': self.branch,
            'status': self.status,
        }
        if self.todo_id is not None:
            result['todo_id'] = self.todo_id
        if self.server_state is not None:
            result['server_state'] = self.server_state
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
