"""module / module_version service.

Business rules: version_no is monotonic per module; publish is an
immutable version insert plus an optional pointer move; rollback repoints
to the version immediately before the current active one, with no insert;
activate promotes any historical version by number, also with no insert.
Versions are never mutated after insert.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from storage.dto.module import Module
from storage.dto.module_version import ModuleVersion
from storage.repository import module as module_repo
from storage.repository import module_version as version_repo
from storage.util import generate_id, get_utc_iso8601_timestamp


# Canonical public demo keys (todo 3158). Route key -> production module slug.
# Deliberately fixed: anonymous callers may not probe arbitrary installed modules.
PUBLIC_DEMO_SLUGS: Dict[str, str] = {
    "chat": "chat",
    "todo": "todo",
    "note": "note",
    "link": "link",
}


@dataclass
class DeleteResult:
    """Outcome of a module delete: version count and both halves' storage keys.

    version_count is the number of deleted version *rows*; storage_keys is the
    flat list of every UI/API bundle key across those rows (a dual-half version
    contributes two keys), so the caller can distinguish versions from objects
    (review finding 5).
    """

    version_count: int = 0
    storage_keys: List[str] = field(default_factory=list)


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


def create_module(user_id: int, slug: str) -> Module:
    existing = module_repo.get_module_by_slug(user_id, slug)
    if existing:
        return existing
    module_id = generate_id()
    return module_repo.create_module(user_id, module_id, slug)


def get_module(user_id: int, module_id: str) -> Optional[Module]:
    return module_repo.get_module(user_id, module_id)


def get_module_by_slug(user_id: int, slug: str) -> Optional[Module]:
    return module_repo.get_module_by_slug(user_id, slug)


def list_modules(user_id: int, enabled_only: bool = False) -> List[Module]:
    return module_repo.list_modules(user_id, enabled_only=enabled_only)


def list_versions(user_id: int, module_id: str) -> List[ModuleVersion]:
    return version_repo.list_versions(user_id, module_id)


def get_version(user_id: int, version_id: str) -> Optional[ModuleVersion]:
    return version_repo.get_version(user_id, version_id)


def get_public_demo(owner_id: int, demo_key: str) -> Optional[Dict]:
    """Minimal projection of an eligible public demo for anonymous lookup.

    Eligibility is fail-closed: the demo_key must be allowlisted, the maintainer
    module must be enabled with an active version, and that version must be
    `ui_public` with UI bytes (sha + storage key). Returns only the fields the
    public browser needs to integrity-check the bundle; never inventory,
    ownership, storage keys, API metadata, or dispatch scope.
    """
    slug = PUBLIC_DEMO_SLUGS.get(demo_key)
    if not slug:
        return None
    module = module_repo.get_module_by_slug(owner_id, slug)
    if not module or not module.enabled or not module.active_version_id:
        return None
    version = version_repo.get_version(owner_id, module.active_version_id)
    if (
        not version
        or not version.ui_public
        or not version.ui_sha256
        or not version.ui_storage_key
    ):
        return None
    return {
        "demo_key": demo_key,
        "slug": slug,
        "version_id": version.version_id,
        "version_no": version.version_no,
        "ui_sha256": version.ui_sha256,
        "min_host_version": version.min_host_version,
    }


def get_public_bundle_version(owner_id: int, version_id: str) -> Optional[ModuleVersion]:
    """Resolve a version that is still eligible for anonymous UI-byte delivery.

    Same gate as get_public_demo's active version: enabled module, currently
    active, ui_public, and UI bytes present. Historical or demoted versions 404
    even if their immutable row still says ui_public.
    """
    version = version_repo.get_version(owner_id, version_id)
    if (
        not version
        or not version.ui_public
        or not version.ui_sha256
        or not version.ui_storage_key
    ):
        return None
    module = module_repo.get_module(owner_id, version.module_id)
    if (
        not module
        or not module.enabled
        or module.active_version_id != version.version_id
    ):
        return None
    return version


def publish(
    user_id: int,
    module_id: str,
    ui_sha256: Optional[str] = None,
    ui_storage_key: Optional[str] = None,
    api_sha256: Optional[str] = None,
    api_storage_key: Optional[str] = None,
    label: Optional[str] = None,
    icon: Optional[str] = None,
    min_host_version: int = 1,
    min_backend_version: Optional[int] = None,
    dispatch_scope: str = "maintainer",
    ui_surfaces: str = "panel",
    ui_public: bool = False,
    source_digest: Optional[str] = None,
    description: Optional[str] = None,
    trace_id: Optional[str] = None,
    activate: bool = True,
) -> Optional[ModuleVersion]:
    """Insert a new immutable version; move the active pointer unless activate=False.

    Returns None when module_id does not name a module owned by user_id,
    so a bogus id cannot insert an orphan version row.
    """
    if not module_repo.get_module(user_id, module_id):
        return None
    next_no = version_repo.get_max_version_no(user_id, module_id) + 1
    version = version_repo.create_version(
        user_id,
        version_id=generate_id(),
        module_id=module_id,
        version_no=next_no,
        ui_sha256=ui_sha256,
        ui_storage_key=ui_storage_key,
        api_sha256=api_sha256,
        api_storage_key=api_storage_key,
        label=label,
        icon=icon,
        min_host_version=min_host_version,
        min_backend_version=min_backend_version,
        dispatch_scope=dispatch_scope,
        ui_surfaces=ui_surfaces,
        ui_public=ui_public,
        source_digest=source_digest,
        built_at=get_utc_iso8601_timestamp(),
        description=description,
        trace_id=trace_id,
    )
    if activate:
        module_repo.set_active_version(user_id, module_id, version.version_id)
    return version


def activate(user_id: int, module_id: str, version_no: int) -> Optional[Module]:
    """Promote a historical version to active by version number. Pointer move only, no rebuild."""
    version = version_repo.get_version_by_no(user_id, module_id, version_no)
    if not version:
        return None
    return module_repo.set_active_version(user_id, module_id, version.version_id)


def rollback(
    user_id: int, module_id: str, from_version_id: Optional[str] = None
) -> Optional[Module]:
    """Repoint to the version immediately before the current active one. Pointer move only.

    `from_version_id`, when given, must match the module's current
    `active_version_id` or this raises RollbackConflictError instead of
    rolling back: the caller (a failure card rendered for a specific version)
    is asserting "roll back from the version I saw fail", and if the pointer
    has since moved (a newer publish landed), honoring that request would
    demote the newer version instead of the stale one the caller meant.
    """
    module = module_repo.get_module(user_id, module_id)
    if not module or not module.active_version_id:
        return None
    if from_version_id is not None and from_version_id != module.active_version_id:
        raise RollbackConflictError(module.active_version_id)
    versions = version_repo.list_versions(user_id, module_id)
    current = next((v for v in versions if v.version_id == module.active_version_id), None)
    if not current:
        return None
    # Greatest version_no below current (list is descending); gap-proof if a
    # pruned version ever leaves a hole in the numbering.
    previous = next((v for v in versions if v.version_no < current.version_no), None)
    if not previous:
        return None
    return module_repo.set_active_version(user_id, module_id, previous.version_id)


def set_enabled(user_id: int, module_id: str, enabled: bool) -> Optional[Module]:
    return module_repo.set_enabled(user_id, module_id, enabled)


def delete_module(user_id: int, module_id: str) -> Optional[DeleteResult]:
    """Hard-delete a module and all of its versions in one transaction.

    BaseEntity has no soft-delete column, so this removes the rows outright.
    The version rows and the module row are deleted in a single repository
    transaction that commits once, while collecting both halves' storage keys
    in memory. Splitting this across two transactions (review finding 5) could
    commit the version delete, then fail before the module delete, stranding
    the module row with an active pointer to a missing version and, on a
    retried delete, permanently losing the keys to every bundle -> their bytes
    become undiscoverable orphans. A single commit makes that ordering
    impossible; any post-commit cleanup failure only orphans bytes, whose keys
    are already gone by design (acceptable).

    Returns a DeleteResult, or None if module_id does not name a module owned
    by user_id.
    """
    row = version_repo.delete_module_with_versions(user_id, module_id)
    if row is None:
        return None
    storage_keys, version_count = row
    return DeleteResult(version_count=version_count, storage_keys=storage_keys)
