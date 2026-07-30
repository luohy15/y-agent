"""Function-based ui_artifact_version repository. Rows are immutable after insert."""

from typing import List, Optional
from storage.entity.ui_artifact_version import UiArtifactVersionEntity
from storage.dto.ui_artifact_version import UiArtifactVersion
from storage.database.base import get_db


def _entity_to_dto(entity: UiArtifactVersionEntity) -> UiArtifactVersion:
    return UiArtifactVersion(
        version_id=entity.version_id,
        artifact_id=entity.artifact_id,
        version_no=entity.version_no,
        sha256=entity.sha256,
        storage_key=entity.storage_key,
        label=entity.label,
        icon=entity.icon,
        min_host_version=entity.min_host_version,
        source_digest=entity.source_digest,
        built_at=entity.built_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def create_version(
    user_id: int,
    version_id: str,
    artifact_id: str,
    version_no: int,
    sha256: str,
    storage_key: str,
    label: Optional[str] = None,
    icon: Optional[str] = None,
    min_host_version: int = 1,
    source_digest: Optional[str] = None,
    built_at: Optional[str] = None,
) -> UiArtifactVersion:
    with get_db() as session:
        entity = UiArtifactVersionEntity(
            user_id=user_id,
            version_id=version_id,
            artifact_id=artifact_id,
            version_no=version_no,
            sha256=sha256,
            storage_key=storage_key,
            label=label,
            icon=icon,
            min_host_version=min_host_version,
            source_digest=source_digest,
            built_at=built_at,
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def get_version(user_id: int, version_id: str) -> Optional[UiArtifactVersion]:
    with get_db() as session:
        entity = session.query(UiArtifactVersionEntity).filter_by(user_id=user_id, version_id=version_id).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_version_by_no(user_id: int, artifact_id: str, version_no: int) -> Optional[UiArtifactVersion]:
    with get_db() as session:
        entity = (
            session.query(UiArtifactVersionEntity)
            .filter_by(user_id=user_id, artifact_id=artifact_id, version_no=version_no)
            .first()
        )
        if not entity:
            return None
        return _entity_to_dto(entity)


def list_versions(user_id: int, artifact_id: str) -> List[UiArtifactVersion]:
    with get_db() as session:
        rows = (
            session.query(UiArtifactVersionEntity)
            .filter_by(user_id=user_id, artifact_id=artifact_id)
            .order_by(UiArtifactVersionEntity.version_no.desc())
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_max_version_no(user_id: int, artifact_id: str) -> int:
    with get_db() as session:
        max_no = (
            session.query(UiArtifactVersionEntity.version_no)
            .filter_by(user_id=user_id, artifact_id=artifact_id)
            .order_by(UiArtifactVersionEntity.version_no.desc())
            .limit(1)
            .scalar()
        )
        return max_no or 0


def delete_versions(user_id: int, artifact_id: str) -> List[str]:
    """Hard-delete every version row for artifact_id, returning their storage_keys."""
    with get_db() as session:
        rows = session.query(UiArtifactVersionEntity).filter_by(user_id=user_id, artifact_id=artifact_id).all()
        storage_keys = [r.storage_key for r in rows]
        for row in rows:
            session.delete(row)
        session.flush()
        return storage_keys
