"""Owner-scoped module tag-carrier claims (todo 3838).

A module version may declare carrier types in `tag_carriers`. Host carrier
names are reserved. A type claimed by another module's active version,
including a disabled module, is rejected at publish and again at activation.
The check and the pointer move share one transaction and one advisory lock
so two publishes cannot both win the same type.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from storage.entity.module import ModuleEntity
from storage.entity.module_version import ModuleVersionEntity

# Keep aligned with storage.service.tag AUTHORING_TYPES | DIRECT_TYPES.
HOST_TAG_CARRIERS = frozenset({
    "todo",
    "note",
    "entity",
    "chat",
    "calendar_event",
    "reminder",
    "routine",
    "link",
    "email",
    "rss_feed",
})

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_CARRIERS = 8
_LOCK_NAMESPACE = 3838


class CarrierConflict(ValueError):
    """The declared carrier set collides with a host type or another module."""


def parse_tag_carriers(value) -> List[str]:
    """Normalize a manifest value to a deduped list. Empty means no claim."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CarrierConflict("tag_carriers must be a JSON list") from exc
    if not isinstance(value, list):
        raise CarrierConflict("tag_carriers must be a list")
    if len(value) > MAX_CARRIERS:
        raise CarrierConflict(f"tag_carriers accepts at most {MAX_CARRIERS} types")
    out: List[str] = []
    for item in value:
        if not isinstance(item, str) or not _NAME.match(item):
            raise CarrierConflict(f"invalid carrier type {item!r}")
        if item in HOST_TAG_CARRIERS:
            raise CarrierConflict(f"carrier type {item} is reserved by the host")
        if item in out:
            raise CarrierConflict(f"duplicate carrier type {item}")
        out.append(item)
    return out


def dump_tag_carriers(carriers: Iterable[str]) -> str:
    return json.dumps(list(carriers), separators=(",", ":"))


def carriers_from_stored(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        return parse_tag_carriers(raw)
    except CarrierConflict:
        return []


def lock_owner(session: Session, user_id: int) -> None:
    """Serialize carrier claims for one owner until the transaction commits.

    Namespace 3838 is distinct from the tag-vocabulary lock (3397). SQLite
    tests skip the statement.
    """
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :owner_id)"),
            {"namespace": _LOCK_NAMESPACE, "owner_id": user_id},
        )


def active_claims(session: Session, user_id: int, *, exclude_module_id: Optional[str] = None):
    """Active-version claims, including disabled modules. Inactive history does not claim."""
    rows = (
        session.query(ModuleEntity.module_id, ModuleVersionEntity.tag_carriers)
        .join(
            ModuleVersionEntity,
            (ModuleVersionEntity.user_id == ModuleEntity.user_id)
            & (ModuleVersionEntity.version_id == ModuleEntity.active_version_id),
        )
        .filter(ModuleEntity.user_id == user_id)
        .all()
    )
    claimed = {}
    for module_id, raw in rows:
        if module_id == exclude_module_id:
            continue
        for name in carriers_from_stored(raw):
            claimed.setdefault(name, module_id)
    return claimed


def assert_available(session: Session, user_id: int, module_id: str, carriers: List[str]) -> None:
    if not carriers:
        return
    lock_owner(session, user_id)
    claimed = active_claims(session, user_id, exclude_module_id=module_id)
    for name in carriers:
        owner = claimed.get(name)
        if owner is not None:
            raise CarrierConflict(f"carrier type {name} is claimed by module {owner}")


def declared_carriers(session: Session, user_id: int, *, enabled_only: bool = False) -> dict:
    """Map carrier type -> owning module slug for active versions.

    Collision checks include disabled modules. Hydration and tag-target
    checks pass enabled_only so a disabled module cannot answer or be tagged.
    """
    query = (
        session.query(ModuleEntity.slug, ModuleVersionEntity.tag_carriers)
        .join(
            ModuleVersionEntity,
            (ModuleVersionEntity.user_id == ModuleEntity.user_id)
            & (ModuleVersionEntity.version_id == ModuleEntity.active_version_id),
        )
        .filter(ModuleEntity.user_id == user_id)
    )
    if enabled_only:
        query = query.filter(ModuleEntity.enabled.is_(True))
    return carrier_map(query.all())


def carrier_map(rows) -> dict:
    """Map carrier type -> slug from (slug, raw tag_carriers) rows."""
    found = {}
    for slug, raw in rows:
        for name in carriers_from_stored(raw):
            found.setdefault(name, slug)
    return found


def is_known_module_carrier(entity_type: str) -> bool:
    """Reserve trusted historical identities on writes, without granting a route.

    Inactive and disabled versions still identify module types. Removing all
    version metadata removes this knowledge; this is not a durable registry.
    Host and never-declared legacy types keep their existing write behavior.
    """
    if entity_type in HOST_TAG_CARRIERS:
        return False
    from storage.database.base import get_db
    from storage.service.user import get_module_maintainer_user_id

    from agent.module_host import ModuleTagUnavailableError

    try:
        maintainer = get_module_maintainer_user_id()
        if maintainer is None:
            raise ModuleTagUnavailableError("carrier authority is not available")
        with get_db() as session:
            rows = session.query(ModuleVersionEntity.tag_carriers).filter(
                ModuleVersionEntity.user_id == maintainer
            ).all()
            return any(entity_type in carriers_from_stored(raw) for (raw,) in rows)
    except ModuleTagUnavailableError:
        raise
    except Exception as exc:
        raise ModuleTagUnavailableError("carrier authority is not available") from exc


def find_carrier_slug(user_id: int, entity_type: str, *, enabled_only: bool = False) -> Optional[str]:
    """Slug of the active module that declares entity_type, if any."""
    from storage.database.base import get_db

    with get_db() as session:
        return declared_carriers(session, user_id, enabled_only=enabled_only).get(entity_type)
