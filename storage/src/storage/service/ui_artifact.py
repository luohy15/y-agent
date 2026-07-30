"""ui_artifact / ui_artifact_version service.

Business rules: version_no is monotonic per artifact; publish is an
immutable version insert plus an optional pointer move; rollback repoints
to the version immediately before the current active one, with no insert;
activate promotes any historical version by number, also with no insert.
Versions are never mutated after insert.
"""

from typing import List, Optional
from storage.dto.ui_artifact import UiArtifact
from storage.dto.ui_artifact_version import UiArtifactVersion
from storage.repository import ui_artifact as artifact_repo
from storage.repository import ui_artifact_version as version_repo
from storage.util import generate_id, get_utc_iso8601_timestamp


class RollbackConflictError(ValueError):
    """Raised when rollback's from_version_id no longer matches the active pointer.

    Between the caller reading the active version and the rollback request
    landing, a newer publish (or another rollback/activate) can move the
    pointer. Rolling back unconditionally at that point would repoint away
    from a version the caller never saw fail.
    """

    def __init__(self, active_version_id: str):
        super().__init__(f"active version has moved to {active_version_id}")
        self.active_version_id = active_version_id


def create_artifact(user_id: int, slug: str, kind: str = "panel") -> UiArtifact:
    existing = artifact_repo.get_artifact_by_slug(user_id, slug)
    if existing:
        return existing
    artifact_id = generate_id()
    return artifact_repo.create_artifact(user_id, artifact_id, slug, kind=kind)


def get_artifact(user_id: int, artifact_id: str) -> Optional[UiArtifact]:
    return artifact_repo.get_artifact(user_id, artifact_id)


def get_artifact_by_slug(user_id: int, slug: str) -> Optional[UiArtifact]:
    return artifact_repo.get_artifact_by_slug(user_id, slug)


def list_artifacts(user_id: int, enabled_only: bool = False) -> List[UiArtifact]:
    return artifact_repo.list_artifacts(user_id, enabled_only=enabled_only)


def list_versions(user_id: int, artifact_id: str) -> List[UiArtifactVersion]:
    return version_repo.list_versions(user_id, artifact_id)


def get_version(user_id: int, version_id: str) -> Optional[UiArtifactVersion]:
    return version_repo.get_version(user_id, version_id)


def publish(
    user_id: int,
    artifact_id: str,
    sha256: str,
    storage_key: str,
    label: Optional[str] = None,
    icon: Optional[str] = None,
    min_host_version: int = 1,
    source_digest: Optional[str] = None,
    activate: bool = True,
) -> Optional[UiArtifactVersion]:
    """Insert a new immutable version; move the active pointer unless activate=False.

    Returns None when artifact_id does not name an artifact owned by user_id,
    so a bogus id cannot insert an orphan version row.
    """
    if not artifact_repo.get_artifact(user_id, artifact_id):
        return None
    next_no = version_repo.get_max_version_no(user_id, artifact_id) + 1
    version = version_repo.create_version(
        user_id,
        version_id=generate_id(),
        artifact_id=artifact_id,
        version_no=next_no,
        sha256=sha256,
        storage_key=storage_key,
        label=label,
        icon=icon,
        min_host_version=min_host_version,
        source_digest=source_digest,
        built_at=get_utc_iso8601_timestamp(),
    )
    if activate:
        artifact_repo.set_active_version(user_id, artifact_id, version.version_id)
    return version


def activate(user_id: int, artifact_id: str, version_no: int) -> Optional[UiArtifact]:
    """Promote a historical version to active by version number. Pointer move only, no rebuild."""
    version = version_repo.get_version_by_no(user_id, artifact_id, version_no)
    if not version:
        return None
    return artifact_repo.set_active_version(user_id, artifact_id, version.version_id)


def rollback(
    user_id: int, artifact_id: str, from_version_id: Optional[str] = None
) -> Optional[UiArtifact]:
    """Repoint to the version immediately before the current active one. Pointer move only.

    `from_version_id`, when given, must match the artifact's current
    `active_version_id` or this raises RollbackConflictError instead of
    rolling back: the caller (a failure card rendered for a specific version)
    is asserting "roll back from the version I saw fail", and if the pointer
    has since moved (a newer publish landed), honoring that request would
    demote the newer version instead of the stale one the caller meant.
    """
    artifact = artifact_repo.get_artifact(user_id, artifact_id)
    if not artifact or not artifact.active_version_id:
        return None
    if from_version_id is not None and from_version_id != artifact.active_version_id:
        raise RollbackConflictError(artifact.active_version_id)
    versions = version_repo.list_versions(user_id, artifact_id)
    current = next((v for v in versions if v.version_id == artifact.active_version_id), None)
    if not current:
        return None
    # Greatest version_no below current (list is descending); gap-proof if a
    # pruned version ever leaves a hole in the numbering.
    previous = next((v for v in versions if v.version_no < current.version_no), None)
    if not previous:
        return None
    return artifact_repo.set_active_version(user_id, artifact_id, previous.version_id)


def set_enabled(user_id: int, artifact_id: str, enabled: bool) -> Optional[UiArtifact]:
    return artifact_repo.set_enabled(user_id, artifact_id, enabled)
