from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class UiArtifact:
    artifact_id: str
    slug: str
    kind: str = "panel"
    active_version_id: Optional[str] = None
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'UiArtifact':
        return cls(
            artifact_id=data['artifact_id'],
            slug=data['slug'],
            kind=data.get('kind', 'panel'),
            active_version_id=data.get('active_version_id'),
            enabled=data.get('enabled', True),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'artifact_id': self.artifact_id,
            'slug': self.slug,
            'kind': self.kind,
            'active_version_id': self.active_version_id,
            'enabled': self.enabled,
        }
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at
        if self.created_at_unix is not None:
            result['created_at_unix'] = self.created_at_unix
        if self.updated_at_unix is not None:
            result['updated_at_unix'] = self.updated_at_unix
        return result
