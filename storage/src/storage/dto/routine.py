from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Routine:
    routine_id: str
    name: str
    schedule: str
    message: str
    description: Optional[str] = None
    target_topic: Optional[str] = None
    target_skill: Optional[str] = None
    work_dir: Optional[str] = None
    backend: Optional[str] = None
    enabled: bool = True
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_chat_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Routine':
        return cls(
            routine_id=data['routine_id'],
            name=data['name'],
            schedule=data['schedule'],
            message=data['message'],
            description=data.get('description'),
            target_topic=data.get('target_topic'),
            target_skill=data.get('target_skill'),
            work_dir=data.get('work_dir'),
            backend=data.get('backend'),
            enabled=data.get('enabled', True),
            last_run_at=data.get('last_run_at'),
            last_run_status=data.get('last_run_status'),
            last_chat_id=data.get('last_chat_id'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'routine_id': self.routine_id,
            'name': self.name,
            'schedule': self.schedule,
            'message': self.message,
            'enabled': self.enabled,
        }
        if self.description is not None:
            result['description'] = self.description
        if self.target_topic is not None:
            result['target_topic'] = self.target_topic
        if self.target_skill is not None:
            result['target_skill'] = self.target_skill
        if self.work_dir is not None:
            result['work_dir'] = self.work_dir
        if self.backend is not None:
            result['backend'] = self.backend
        if self.last_run_at is not None:
            result['last_run_at'] = self.last_run_at
        if self.last_run_status is not None:
            result['last_run_status'] = self.last_run_status
        if self.last_chat_id is not None:
            result['last_chat_id'] = self.last_chat_id
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
