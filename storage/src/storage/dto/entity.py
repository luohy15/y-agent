from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Entity:
    entity_id: str
    name: str
    type: str
    front_matter: Optional[Dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'Entity':
        return cls(
            entity_id=data['entity_id'],
            name=data['name'],
            type=data['type'],
            front_matter=data.get('front_matter'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'entity_id': self.entity_id,
            'name': self.name,
            'type': self.type,
        }
        if self.front_matter is not None:
            result['front_matter'] = self.front_matter
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
