from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TraceParticipant:
    chat_id: str
    skill: str
    work_dir: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'TraceParticipant':
        return cls(
            chat_id=data['chat_id'],
            skill=data['skill'],
            work_dir=data.get('work_dir'),
        )

    def to_dict(self) -> Dict:
        result: Dict = {'chat_id': self.chat_id, 'skill': self.skill}
        if self.work_dir is not None:
            result['work_dir'] = self.work_dir
        return result


@dataclass
class Trace:
    trace_id: str
    participants: List[TraceParticipant] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Trace':
        return cls(
            trace_id=data['trace_id'],
            participants=[TraceParticipant.from_dict(p) for p in data.get('participants', [])],
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
        )

    def to_dict(self) -> Dict:
        return {
            'trace_id': self.trace_id,
            'participants': [p.to_dict() for p in self.participants],
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
