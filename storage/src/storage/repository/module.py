"""Function-based module repository."""

from typing import List, Optional
from storage.entity.module import ModuleEntity
from storage.dto.module import Module
from storage.database.base import get_db


def _entity_to_dto(entity: ModuleEntity) -> Module:
    return Module(
        module_id=entity.module_id,
        slug=entity.slug,
        active_version_id=entity.active_version_id,
        enabled=entity.enabled,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def create_module(user_id: int, module_id: str, slug: str) -> Module:
    with get_db() as session:
        entity = ModuleEntity(
            user_id=user_id,
            module_id=module_id,
            slug=slug,
            enabled=True,
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def get_module(user_id: int, module_id: str) -> Optional[Module]:
    with get_db() as session:
        entity = session.query(ModuleEntity).filter_by(user_id=user_id, module_id=module_id).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_module_by_slug(user_id: int, slug: str) -> Optional[Module]:
    with get_db() as session:
        entity = session.query(ModuleEntity).filter_by(user_id=user_id, slug=slug).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def list_modules(user_id: int, enabled_only: bool = False) -> List[Module]:
    with get_db() as session:
        query = session.query(ModuleEntity).filter_by(user_id=user_id)
        if enabled_only:
            query = query.filter_by(enabled=True)
        rows = query.order_by(ModuleEntity.created_at_unix.asc()).all()
        return [_entity_to_dto(r) for r in rows]


def set_active_version(user_id: int, module_id: str, version_id: Optional[str]) -> Optional[Module]:
    with get_db() as session:
        entity = session.query(ModuleEntity).filter_by(user_id=user_id, module_id=module_id).first()
        if not entity:
            return None
        entity.active_version_id = version_id
        session.flush()
        return _entity_to_dto(entity)


def set_enabled(user_id: int, module_id: str, enabled: bool) -> Optional[Module]:
    with get_db() as session:
        entity = session.query(ModuleEntity).filter_by(user_id=user_id, module_id=module_id).first()
        if not entity:
            return None
        entity.enabled = enabled
        session.flush()
        return _entity_to_dto(entity)
