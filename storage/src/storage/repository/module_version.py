"""Function-based module_version repository. Rows are immutable after insert."""

from typing import List, Optional, Tuple
from storage.entity.module import ModuleEntity
from storage.entity.module_version import ModuleVersionEntity
from storage.dto.module_version import ModuleVersion
from storage.database.base import get_db


def _entity_to_dto(entity: ModuleVersionEntity) -> ModuleVersion:
    return ModuleVersion(
        version_id=entity.version_id,
        module_id=entity.module_id,
        version_no=entity.version_no,
        ui_sha256=entity.ui_sha256,
        ui_storage_key=entity.ui_storage_key,
        api_sha256=entity.api_sha256,
        api_storage_key=entity.api_storage_key,
        label=entity.label,
        icon=entity.icon,
        min_host_version=entity.min_host_version,
        min_backend_version=entity.min_backend_version,
        source_digest=entity.source_digest,
        built_at=entity.built_at,
        description=entity.description,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def create_version(
    user_id: int,
    version_id: str,
    module_id: str,
    version_no: int,
    ui_sha256: Optional[str] = None,
    ui_storage_key: Optional[str] = None,
    api_sha256: Optional[str] = None,
    api_storage_key: Optional[str] = None,
    label: Optional[str] = None,
    icon: Optional[str] = None,
    min_host_version: int = 1,
    min_backend_version: Optional[int] = None,
    source_digest: Optional[str] = None,
    built_at: Optional[str] = None,
    description: Optional[str] = None,
) -> ModuleVersion:
    with get_db() as session:
        entity = ModuleVersionEntity(
            user_id=user_id,
            version_id=version_id,
            module_id=module_id,
            version_no=version_no,
            ui_sha256=ui_sha256,
            ui_storage_key=ui_storage_key,
            api_sha256=api_sha256,
            api_storage_key=api_storage_key,
            label=label,
            icon=icon,
            min_host_version=min_host_version,
            min_backend_version=min_backend_version,
            source_digest=source_digest,
            built_at=built_at,
            description=description,
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def get_version(user_id: int, version_id: str) -> Optional[ModuleVersion]:
    with get_db() as session:
        entity = session.query(ModuleVersionEntity).filter_by(user_id=user_id, version_id=version_id).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_version_by_no(user_id: int, module_id: str, version_no: int) -> Optional[ModuleVersion]:
    with get_db() as session:
        entity = (
            session.query(ModuleVersionEntity)
            .filter_by(user_id=user_id, module_id=module_id, version_no=version_no)
            .first()
        )
        if not entity:
            return None
        return _entity_to_dto(entity)


def list_versions(user_id: int, module_id: str) -> List[ModuleVersion]:
    with get_db() as session:
        rows = (
            session.query(ModuleVersionEntity)
            .filter_by(user_id=user_id, module_id=module_id)
            .order_by(ModuleVersionEntity.version_no.desc())
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_max_version_no(user_id: int, module_id: str) -> int:
    with get_db() as session:
        max_no = (
            session.query(ModuleVersionEntity.version_no)
            .filter_by(user_id=user_id, module_id=module_id)
            .order_by(ModuleVersionEntity.version_no.desc())
            .limit(1)
            .scalar()
        )
        return max_no or 0


def delete_module_with_versions(user_id: int, module_id: str) -> Optional[Tuple[List[str], int]]:
    """Delete every version row AND the module row in one transaction.

    get_db commits on clean exit, so all of this is a single commit: a failure
    anywhere rolls the whole delete back, which is what keeps the module's
    bundle lookup keys from being erased before the module deletion is durable
    (review finding 5). Returns (storage_keys, version_count) where
    storage_keys is the flat list of every UI + API key across the deleted
    version rows, or None if module_id does not name a module owned by user_id.
    """
    with get_db() as session:
        module = session.query(ModuleEntity).filter_by(user_id=user_id, module_id=module_id).first()
        if not module:
            return None
        rows = session.query(ModuleVersionEntity).filter_by(user_id=user_id, module_id=module_id).all()
        storage_keys: List[str] = []
        for r in rows:
            if r.ui_storage_key:
                storage_keys.append(r.ui_storage_key)
            if r.api_storage_key:
                storage_keys.append(r.api_storage_key)
        version_count = len(rows)
        for row in rows:
            session.delete(row)
        session.delete(module)
        session.flush()
        return storage_keys, version_count
