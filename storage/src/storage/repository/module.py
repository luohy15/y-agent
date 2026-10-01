"""Function-based module repository."""

from typing import List, Optional, Tuple
from storage.entity.module import ModuleEntity
from storage.entity.module_version import ModuleVersionEntity
from storage.dto.module import Module
from storage.dto.module_version import ModuleVersion
from storage.database.base import get_db
from storage.repository.module_version import _entity_to_dto as _version_to_dto


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


def get_active_version_by_slug(
    user_id: int, slug: str
) -> Tuple[Optional[Module], Optional[ModuleVersion]]:
    """Module row plus its active version, or (None, None) when the slug is absent.

    One outer join: a module with no matching version still returns the module
    and a None version so the caller can tell "no such module" from "pointer
    does not resolve".
    """
    with get_db() as session:
        row = (
            session.query(ModuleEntity, ModuleVersionEntity)
            .outerjoin(
                ModuleVersionEntity,
                (ModuleVersionEntity.user_id == ModuleEntity.user_id)
                & (ModuleVersionEntity.version_id == ModuleEntity.active_version_id),
            )
            .filter(ModuleEntity.user_id == user_id, ModuleEntity.slug == slug)
            .first()
        )
        if row is None:
            return None, None
        module_entity, version_entity = row
        version = _version_to_dto(version_entity) if version_entity is not None else None
        return _entity_to_dto(module_entity), version


def list_modules(user_id: int, enabled_only: bool = False) -> List[Module]:
    with get_db() as session:
        query = session.query(ModuleEntity).filter_by(user_id=user_id)
        if enabled_only:
            query = query.filter_by(enabled=True)
        rows = query.order_by(ModuleEntity.created_at_unix.asc()).all()
        return [_entity_to_dto(r) for r in rows]


def list_modules_with_active_versions(
    user_id: int, enabled_only: bool = False
) -> List[Tuple[Module, Optional[ModuleVersion]]]:
    """Owner modules plus the active version, one outer join.

    A missing or dangling active_version_id yields None for the version.
    The version match is (user_id, version_id), so another owner's row with
    the same version_id cannot attach. Same filter and order as list_modules.
    """
    with get_db() as session:
        query = (
            session.query(ModuleEntity, ModuleVersionEntity)
            .outerjoin(
                ModuleVersionEntity,
                (ModuleVersionEntity.user_id == ModuleEntity.user_id)
                & (ModuleVersionEntity.version_id == ModuleEntity.active_version_id),
            )
            .filter(ModuleEntity.user_id == user_id)
        )
        if enabled_only:
            # filter_by is ambiguous once module_version is in the query.
            query = query.filter(ModuleEntity.enabled.is_(True))
        rows = query.order_by(ModuleEntity.created_at_unix.asc()).all()
        result = []
        for module_entity, version_entity in rows:
            version = _version_to_dto(version_entity) if version_entity is not None else None
            result.append((_entity_to_dto(module_entity), version))
        return result


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
