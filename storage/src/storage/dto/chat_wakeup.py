from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ChatWakeup:
    """Public projection of one durable wakeup receipt (todo 3655)."""

    wakeup_id: str
    user_id: str  # public account id
    chat_id: str
    trace_id: str
    message: str
    due_at_unix: int
    status: str = "pending"
    from_chat_id: Optional[str] = None
    from_topic: Optional[str] = None
    enqueue_needed: Optional[bool] = None
    delivery_attempts: int = 0
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    def to_dict(self) -> Dict:
        """Owner-only projection: the caller is always the registering
        account. No integer id ever appears here."""
        result = {
            'wakeup_id': self.wakeup_id,
            'user_id': self.user_id,
            'chat_id': self.chat_id,
            'trace_id': self.trace_id,
            'message': self.message,
            'due_at_unix': self.due_at_unix,
            'status': self.status,
            'delivery_attempts': self.delivery_attempts,
        }
        if self.from_chat_id is not None:
            result['from_chat_id'] = self.from_chat_id
        if self.from_topic is not None:
            result['from_topic'] = self.from_topic
        if self.enqueue_needed is not None:
            result['enqueue_needed'] = self.enqueue_needed
        if self.last_error is not None:
            result['last_error'] = self.last_error
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
