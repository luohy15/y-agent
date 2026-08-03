from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ModuleVersion:
    version_id: str
    module_id: str
    version_no: int
    ui_sha256: Optional[str] = None
    ui_storage_key: Optional[str] = None
    api_sha256: Optional[str] = None
    api_storage_key: Optional[str] = None
    label: Optional[str] = None
    icon: Optional[str] = None
    min_host_version: int = 1
    min_backend_version: Optional[int] = None
    source_digest: Optional[str] = None
    built_at: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ModuleVersion':
        return cls(
            version_id=data['version_id'],
            module_id=data['module_id'],
            version_no=data['version_no'],
            ui_sha256=data.get('ui_sha256'),
            ui_storage_key=data.get('ui_storage_key'),
            api_sha256=data.get('api_sha256'),
            api_storage_key=data.get('api_storage_key'),
            label=data.get('label'),
            icon=data.get('icon'),
            min_host_version=data.get('min_host_version', 1),
            min_backend_version=data.get('min_backend_version'),
            source_digest=data.get('source_digest'),
            built_at=data.get('built_at'),
            description=data.get('description'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            created_at_unix=data.get('created_at_unix'),
            updated_at_unix=data.get('updated_at_unix'),
        )

    def to_dict(self) -> Dict:
        result = {
            'version_id': self.version_id,
            'module_id': self.module_id,
            'version_no': self.version_no,
            'ui_sha256': self.ui_sha256,
            'ui_storage_key': self.ui_storage_key,
            'api_sha256': self.api_sha256,
            'api_storage_key': self.api_storage_key,
            'label': self.label,
            'icon': self.icon,
            'min_host_version': self.min_host_version,
            'min_backend_version': self.min_backend_version,
            'source_digest': self.source_digest,
            'built_at': self.built_at,
            'description': self.description,
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
