"""Function-based ui_artifact repository."""

from typing import List, Optional
from storage.entity.ui_artifact import UiArtifactEntity
from storage.dto.ui_artifact import UiArtifact
from storage.database.base import get_db


def _entity_to_dto(entity: UiArtifactEntity) -> UiArtifact:
    return UiArtifact(
        artifact_id=entity.artifact_id,
        slug=entity.slug,
        kind=entity.kind,
        active_version_id=entity.active_version_id,
        enabled=entity.enabled,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def create_artifact(user_id: int, artifact_id: str, slug: str, kind: str = "panel") -> UiArtifact:
    with get_db() as session:
        entity = UiArtifactEntity(
            user_id=user_id,
            artifact_id=artifact_id,
            slug=slug,
            kind=kind,
            enabled=True,
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def get_artifact(user_id: int, artifact_id: str) -> Optional[UiArtifact]:
    with get_db() as session:
        entity = session.query(UiArtifactEntity).filter_by(user_id=user_id, artifact_id=artifact_id).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_artifact_by_slug(user_id: int, slug: str) -> Optional[UiArtifact]:
    with get_db() as session:
        entity = session.query(UiArtifactEntity).filter_by(user_id=user_id, slug=slug).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def list_artifacts(user_id: int, enabled_only: bool = False) -> List[UiArtifact]:
    with get_db() as session:
        query = session.query(UiArtifactEntity).filter_by(user_id=user_id)
        if enabled_only:
            query = query.filter_by(enabled=True)
        rows = query.order_by(UiArtifactEntity.created_at_unix.asc()).all()
        return [_entity_to_dto(r) for r in rows]


def set_active_version(user_id: int, artifact_id: str, version_id: Optional[str]) -> Optional[UiArtifact]:
    with get_db() as session:
        entity = session.query(UiArtifactEntity).filter_by(user_id=user_id, artifact_id=artifact_id).first()
        if not entity:
            return None
        entity.active_version_id = version_id
        session.flush()
        return _entity_to_dto(entity)


def set_enabled(user_id: int, artifact_id: str, enabled: bool) -> Optional[UiArtifact]:
    with get_db() as session:
        entity = session.query(UiArtifactEntity).filter_by(user_id=user_id, artifact_id=artifact_id).first()
        if not entity:
            return None
        entity.enabled = enabled
        session.flush()
        return _entity_to_dto(entity)
