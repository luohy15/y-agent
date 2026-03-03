from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class Email:
    email_id: str
    subject: Optional[str] = None
    from_addr: str = ""
    to_addrs: Optional[List[str]] = None
    cc_addrs: Optional[List[str]] = None
    bcc_addrs: Optional[List[str]] = None
    date: int = 0
    content: Optional[str] = None
    thread_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Email':
        return cls(
            email_id=data['email_id'],
            subject=data.get('subject'),
            from_addr=data.get('from_addr', ''),
            to_addrs=data.get('to_addrs'),
            cc_addrs=data.get('cc_addrs'),
            bcc_addrs=data.get('bcc_addrs'),
            date=data.get('date', 0),
            content=data.get('content'),
            thread_id=data.get('thread_id'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'email_id': self.email_id,
            'from_addr': self.from_addr,
            'date': self.date,
        }
        if self.subject is not None:
            result['subject'] = self.subject
        if self.to_addrs is not None:
            result['to_addrs'] = self.to_addrs
        if self.cc_addrs is not None:
            result['cc_addrs'] = self.cc_addrs
        if self.bcc_addrs is not None:
            result['bcc_addrs'] = self.bcc_addrs
        if self.content is not None:
            result['content'] = self.content
        if self.thread_id is not None:
            result['thread_id'] = self.thread_id
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
