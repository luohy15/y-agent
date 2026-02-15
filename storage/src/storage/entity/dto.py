"""Data Transfer Objects (dataclass DTOs) for bot, prompt, and chat domains."""

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Union, Iterable
from datetime import datetime
from storage.util import get_iso8601_timestamp

# Invisible Unicode characters that Safari renders as boxes
_INVISIBLE_RE = re.compile(
    '[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f'
    '\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff\ufff9-\ufffc]'
)

def _strip_invisible(s: str) -> str:
    return _INVISIBLE_RE.sub('', s)

# ── Bot ──

DEFAULT_OPENROUTER_CONFIG = {
    "provider": {
        "sort": "throughput"
    }
}

@dataclass
class BotConfig:
    name: str
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_type: Optional[str] = None
    model: str = ""
    description: Optional[str] = None
    openrouter_config: Optional[Dict] = None
    prompts: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    custom_api_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'BotConfig':
        return cls(**data)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

# ── VM ──

@dataclass
class VmConfig:
    api_token: str = ""
    vm_name: str = ""

    @classmethod
    def from_dict(cls, data: Dict) -> 'VmConfig':
        return cls(**data)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

# ── Chat ──

@dataclass
class ContentPart:
    text: str
    type: str = "text"

@dataclass
class Message:
    role: str
    content: Union[str, Iterable[ContentPart]]
    timestamp: str
    unix_timestamp: int
    reasoning_content: Optional[str] = None
    reasoning_effort: Optional[str] = None
    links: Optional[List[str]] = None
    images: Optional[List[str]] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    id: Optional[str] = None
    parent_id: Optional[str] = None
    server: Optional[str] = None
    tool: Optional[str] = None
    arguments: Optional[Dict[str, Union[str, int, float, bool, Dict, List]]] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Message':
        unix_timestamp = data.get('unix_timestamp')
        if unix_timestamp is None:
            dt = datetime.strptime(data['timestamp'].split('+')[0], "%Y-%m-%dT%H:%M:%S")
            unix_timestamp = int(dt.timestamp() * 1000)
        else:
            unix_timestamp = int(unix_timestamp)

        content = data['content']
        if isinstance(content, str):
            content = _strip_invisible(content)
        elif isinstance(content, list):
            content = [ContentPart(**part) if isinstance(part, dict) else part for part in content]
            for part in content:
                if isinstance(part, ContentPart):
                    part.text = _strip_invisible(part.text)

        return cls(
            role=data['role'],
            content=content,
            reasoning_content=data.get('reasoning_content'),
            reasoning_effort=data.get('reasoning_effort'),
            timestamp=data['timestamp'],
            unix_timestamp=unix_timestamp,
            provider=data.get('provider'),
            links=data.get('links'),
            images=data.get('images'),
            model=data.get('model'),
            id=data.get('id'),
            parent_id=data.get('parent_id'),
            server=data.get('server'),
            tool=data.get('tool'),
            arguments=data.get('arguments'),
            tool_calls=data.get('tool_calls'),
            tool_call_id=data.get('tool_call_id'),
        )

    def to_dict(self) -> Dict:
        if isinstance(self.content, list):
            content = [{'type': part.type, 'text': part.text} for part in self.content]
        else:
            content = self.content

        result = {
            'role': self.role,
            'content': content,
            'timestamp': self.timestamp,
            'unix_timestamp': self.unix_timestamp
        }
        if self.reasoning_content is not None:
            result['reasoning_content'] = self.reasoning_content
        if self.reasoning_effort is not None:
            result['reasoning_effort'] = self.reasoning_effort
        if self.id is not None:
            result['id'] = self.id
        if self.parent_id is not None:
            result['parent_id'] = self.parent_id
        if self.links is not None:
            result['links'] = self.links
        if self.images is not None:
            result['images'] = self.images
        if self.model is not None:
            result['model'] = self.model
        if self.provider is not None:
            result['provider'] = self.provider
        if self.server is not None:
            result['server'] = self.server
        if self.tool is not None:
            result['tool'] = self.tool
        if self.arguments is not None:
            result['arguments'] = self.arguments
        if self.tool_calls is not None:
            result['tool_calls'] = self.tool_calls
        if self.tool_call_id is not None:
            result['tool_call_id'] = self.tool_call_id
        return result

@dataclass
class Chat:
    id: str
    create_time: str
    update_time: str
    messages: List[Message]
    external_id: Optional[str] = None
    content_hash: Optional[str] = None
    origin_chat_id: Optional[str] = None
    origin_message_id: Optional[str] = None
    auto_approve: bool = False
    interrupted: bool = False

    @classmethod
    def from_dict(cls, data: Dict) -> 'Chat':
        return cls(
            id=data['id'],
            create_time=data['create_time'],
            update_time=data['update_time'],
            messages=sorted(
                [Message.from_dict(m) for m in data['messages'] if m['role'] != 'system'],
                key=lambda x: (x.unix_timestamp)
            ),
            external_id=data.get('external_id'),
            content_hash=data.get('content_hash'),
            origin_chat_id=data.get('origin_chat_id'),
            origin_message_id=data.get('origin_message_id') or data.get('selected_message_id'),
            auto_approve=data.get('auto_approve', False),
            interrupted=data.get('interrupted', False),
        )

    def to_dict(self) -> Dict:
        result = {
            'create_time': self.create_time,
            'id': self.id,
            'update_time': self.update_time,
            'messages': [m.to_dict() for m in self.messages]
        }
        if self.external_id is not None:
            result['external_id'] = self.external_id
        if self.content_hash is not None:
            result['content_hash'] = self.content_hash
        if self.origin_chat_id is not None:
            result['origin_chat_id'] = self.origin_chat_id
        if self.origin_message_id is not None:
            result['origin_message_id'] = self.origin_message_id
        if self.auto_approve:
            result['auto_approve'] = self.auto_approve
        if self.interrupted:
            result['interrupted'] = self.interrupted
        return result

    def update_messages(self, messages: List[Message]) -> None:
        self.messages = sorted(
            [msg for msg in messages if msg.role != 'system'],
            key=lambda x: (x.unix_timestamp)
        )
        self.update_time = get_iso8601_timestamp()
