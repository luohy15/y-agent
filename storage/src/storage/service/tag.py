"""Tag service — cross-entity tag projection and lookup.

sync_tags() is the shared projection helper carrier slices (note/entity/todo
authoring surfaces and direct entity_tag carriers) call to keep entity_tag in
sync with their own tag source of truth. Email is the exception: its service
validates canonical thread keys and existing vocabulary before it writes.

Phase-2 carrier modules register their batch hydration resolvers via
register_resolver() from their own service module (do not edit the built-in
_RESOLVERS dict from parallel batches). get_by_tag() lazy-imports
storage.service.<entity_type> by convention so self-registration runs even
when only the tag CLI/API was loaded. Lookup hydrates one batch per
entity_type (todo 3226) so SQL work stays O(types), not O(rows).

Todo 3219 adds plan_rename() / apply_rename(): a single-session coordinated
rename/merge over authoring fields + entity_tag. Carriers are found through
entity_tag (exact source value); the CLI owns on-disk front matter.

Todo 3290 adds create_vocabulary(): a durable, owner-scoped canonical
tag_vocabulary row that can exist with zero entity_tag uses. list_vocabulary()
now left-joins tag_vocabulary with entity_tag so a newly created tag appears
with count 0, and apply_rename() keeps tag_vocabulary identity coordinated
with a rename/merge (registers the target, retires the source spelling).
"""

import hashlib
import importlib
import json
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from storage.database.base import get_db
from storage.entity.entity import EntityEntity
from storage.entity.entity_tag import EntityTagEntity
from storage.entity.note import NoteEntity
from storage.entity.tag_vocabulary import TagVocabularyEntity
from storage.entity.todo import TodoEntity
from storage.repository import entity_tag as tag_repo
from storage.repository import tag_vocabulary as vocabulary_repo
# Re-export write-time normalizers so carriers can keep authoring surfaces
# (todo.tags / front_matter.tags) in the same canonical form as entity_tag.
from storage.repository.entity_tag import normalize_tag, normalize_tags  # noqa: F401
from storage.service import entity as entity_service
from storage.service import note as note_service
from storage.service import todo as todo_service
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp

# (user_id, entity_ids) -> {entity_id: {"id": public_id, "title": display, ...}}
# Missing ids are omitted; get_by_tag falls back to {"id": entity_id}.
Resolver = Callable[[int, List[str]], Dict[str, Dict]]

AUTHORING_TYPES = frozenset({"todo", "note", "entity"})
DIRECT_TYPES = frozenset({
    "chat",
    "calendar_event",
    "reminder",
    "routine",
    "link",
    "email",
    "rss_feed",
})


class TagRenameError(ValueError):
    """Caller input failed for a tag rename/merge."""


class TagRenameConflict(RuntimeError):
    """Live state drifted from the planned rename/merge (map to HTTP 409)."""


def sync_tags(user_id: int, entity_type: str, entity_id: str, tags: List[str]) -> None:
    """Reconcile the entity_tag projection for one (entity_type, entity_id) to `tags`."""
    tag_repo.sync_tags(user_id, entity_type, entity_id, tags)


def add_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    if entity_type == "email":
        from storage.service import email as email_service
        return email_service.add_tag(user_id, entity_id, tag)
    return tag_repo.add_tag(user_id, entity_type, entity_id, tag)


def remove_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    if entity_type == "email":
        from storage.service import email as email_service
        return email_service.remove_tag(user_id, entity_id, tag)
    return tag_repo.remove_tag(user_id, entity_type, entity_id, tag)


def list_tags(user_id: int, entity_type: str, entity_id: str) -> List[str]:
    return tag_repo.list_tags(user_id, entity_type, entity_id)


def delete_for_entity(user_id: int, entity_type: str, entity_id: str) -> int:
    return tag_repo.delete_for_entity(user_id, entity_type, entity_id)


def _resolve_todos(user_id: int, entity_ids: List[str]) -> Dict[str, Dict]:
    if not entity_ids:
        return {}
    # updated_at_unix is the todo row's own timestamp (not effective chat activity).
    # Present so presentation clients (tag module) can sort without a second fetch.
    return {
        todo_id: {
            "id": todo.todo_id,
            "title": todo.name,
            "updated_at_unix": todo.updated_at_unix,
        }
        for todo_id, todo in todo_service.find_todos_by_ids(user_id, entity_ids).items()
    }


def _resolve_notes(user_id: int, entity_ids: List[str]) -> Dict[str, Dict]:
    if not entity_ids:
        return {}
    return {
        note.note_id: {"id": note.note_id, "title": note.content_key}
        for note in note_service.get_notes_by_ids(user_id, entity_ids)
    }


def _resolve_entities(user_id: int, entity_ids: List[str]) -> Dict[str, Dict]:
    if not entity_ids:
        return {}
    return {
        entity.entity_id: {"id": entity.entity_id, "title": entity.name}
        for entity in entity_service.get_entities_by_ids(user_id, entity_ids)
    }


# Built-in resolvers for the three existing authoring-surface carriers (S0).
# Phase-2 carriers register via register_resolver() from their own modules.
_RESOLVERS: Dict[str, Resolver] = {
    "todo": _resolve_todos,
    "note": _resolve_notes,
    "entity": _resolve_entities,
}


def register_resolver(entity_type: str, resolver: Resolver) -> None:
    """Register a batch hydration resolver for an entity_type (idempotent overwrite).

    Call from the carrier's own service module at import time so parallel
    phase-2 batches never need to edit this file's resolver dict. The resolver
    receives (user_id, entity_ids) and returns {entity_id: hydrated_row}.
    """
    _RESOLVERS[entity_type] = resolver


def _get_resolver(entity_type: str) -> Optional[Resolver]:
    """Return a registered resolver, lazy-importing storage.service.<type> first."""
    resolver = _RESOLVERS.get(entity_type)
    if resolver is not None:
        return resolver
    try:
        importlib.import_module(f"storage.service.{entity_type}")
    except ImportError:
        return None
    return _RESOLVERS.get(entity_type)


def get_by_tag(user_id: int, tag: str, prefix: bool = False) -> Dict[str, List[Dict]]:
    """Find everything tagged `tag`, grouped by entity_type and hydrated through
    each type's own service (public id + display title). entity_types without a
    registered resolver fall back to {"id": entity_id}. Output order within each
    type matches the projection query order.
    """
    pairs = tag_repo.find_by_tag(user_id, tag, prefix=prefix)
    ids_by_type: Dict[str, List[str]] = defaultdict(list)
    for entity_type, entity_id in pairs:
        ids_by_type[entity_type].append(entity_id)

    hydrated_by_type: Dict[str, Dict[str, Dict]] = {}
    for entity_type, entity_ids in ids_by_type.items():
        resolver = _get_resolver(entity_type)
        if resolver is None:
            hydrated_by_type[entity_type] = {}
            continue
        hydrated_by_type[entity_type] = resolver(user_id, entity_ids) or {}

    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entity_type, entity_id in pairs:
        item = hydrated_by_type.get(entity_type, {}).get(entity_id)
        grouped[entity_type].append(item if item is not None else {"id": entity_id})
    return dict(grouped)


def list_vocabulary(user_id: int) -> List[Tuple[str, int]]:
    """Durable vocabulary tags for the user with usage counts (0 for an unused tag).

    Left-joins tag_vocabulary with entity_tag rather than reading
    entity_tag.distinct_tags() directly, so a tag created via
    create_vocabulary() with no carrier yet still appears, with count 0.
    """
    with get_db() as session:
        rows = (
            session.query(TagVocabularyEntity.tag, func.count(EntityTagEntity.id))
            .outerjoin(
                EntityTagEntity,
                (EntityTagEntity.user_id == TagVocabularyEntity.user_id)
                & (EntityTagEntity.tag == TagVocabularyEntity.tag),
            )
            .filter(TagVocabularyEntity.user_id == user_id)
            .group_by(TagVocabularyEntity.tag)
            .order_by(TagVocabularyEntity.tag)
            .all()
        )
        return [(row[0], row[1]) for row in rows]


class TagVocabularyError(ValueError):
    """Caller input failed canonical vocabulary syntax validation."""


_TAG_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_tag_syntax(tag: str) -> None:
    """Raise TagVocabularyError unless `tag` is slash-delimited lowercase hyphen slugs.

    Each `/`-delimited segment must match `[a-z0-9]+(?:-[a-z0-9]+)*`: empty
    segments (so leading/trailing/doubled slashes are rejected), whitespace,
    punctuation other than `-`, and leading/trailing hyphens are all invalid.
    Semantic rules (identity vs topic, singular/plural, usefulness) are human
    policy and are deliberately not checked here.
    """
    for segment in tag.split("/"):
        if not segment or not _TAG_SEGMENT_RE.match(segment):
            raise TagVocabularyError(
                f"invalid tag syntax: {tag!r} (segment {segment!r} must be "
                "lowercase alphanumeric words joined by single hyphens)"
            )


def create_vocabulary(user_id: int, tag: str) -> Dict[str, object]:
    """Normalize, validate, and idempotently register a canonical vocabulary tag.

    Returns {"tag": canonical, "created": bool}; `created` is False when the
    canonical spelling already exists (including when a concurrent create won
    the uniqueness race). Raises TagVocabularyError on blank or syntactically
    invalid input, and never writes on that path.
    """
    canonical = normalize_tag(tag)
    if not canonical:
        raise TagVocabularyError("tag must not be blank")
    _validate_tag_syntax(canonical)
    canonical, created = vocabulary_repo.create(user_id, canonical)
    return {"tag": canonical, "created": created}


# Authoring-surface carriers that predate entity_tag and need a one-shot backfill.
_BACKFILL_TYPES = ("note", "entity", "todo")
_PAGE_SIZE = 200


def _tags_from_front_matter(front_matter: Optional[Dict]) -> List[str]:
    if not isinstance(front_matter, dict):
        return []
    return normalize_tags(front_matter.get("tags"))


def _iter_notes(user_id: int):
    offset = 0
    while True:
        batch = note_service.list_notes(user_id, limit=_PAGE_SIZE, offset=offset)
        if not batch:
            break
        for note in batch:
            yield note
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE


def _iter_entities(user_id: int):
    offset = 0
    while True:
        batch = entity_service.list_entities(user_id, limit=_PAGE_SIZE, offset=offset)
        if not batch:
            break
        for entity in batch:
            yield entity
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE


def _iter_todos(user_id: int):
    offset = 0
    while True:
        batch = todo_service.list_todos(user_id, limit=_PAGE_SIZE, offset=offset)
        if not batch:
            break
        for todo in batch:
            yield todo
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE


def backfill_tags(
    user_id: int,
    *,
    dry_run: bool = False,
    entity_types: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Dict:
    """Project pre-existing authoring-surface tags into entity_tag.

    Source of truth (DB columns, not EC2 markdown files):
      - note:   note.front_matter.tags
      - entity: entity.front_matter.tags
      - todo:   todo.tags

    Uses sync_tags so re-runs are idempotent (reconcile, no duplicates).
    Skips items with no tags (does not wipe rows added via y tag add alone).
    Scoped to one user. Direct carriers have no authoring-column backfill.
    """
    wanted = set(entity_types) if entity_types else set(_BACKFILL_TYPES)
    unknown = wanted - set(_BACKFILL_TYPES)
    if unknown:
        raise ValueError(f"unsupported backfill types: {sorted(unknown)}; allowed: {list(_BACKFILL_TYPES)}")

    by_type: Dict[str, Dict] = {}
    total_synced = 0
    total_tag_rows = 0

    if "note" in wanted:
        stats = {"scanned": 0, "with_tags": 0, "synced": 0, "tag_rows": 0}
        for note in _iter_notes(user_id):
            stats["scanned"] += 1
            tags = _tags_from_front_matter(note.front_matter)
            if not tags:
                continue
            stats["with_tags"] += 1
            if not dry_run:
                tag_repo.sync_tags(user_id, "note", note.note_id, tags)
            stats["synced"] += 1
            stats["tag_rows"] += len(tags)
            if limit is not None and stats["synced"] >= limit:
                break
        by_type["note"] = stats
        total_synced += stats["synced"]
        total_tag_rows += stats["tag_rows"]

    if "entity" in wanted:
        stats = {"scanned": 0, "with_tags": 0, "synced": 0, "tag_rows": 0}
        for entity in _iter_entities(user_id):
            stats["scanned"] += 1
            tags = _tags_from_front_matter(entity.front_matter)
            if not tags:
                continue
            stats["with_tags"] += 1
            if not dry_run:
                tag_repo.sync_tags(user_id, "entity", entity.entity_id, tags)
            stats["synced"] += 1
            stats["tag_rows"] += len(tags)
            if limit is not None and stats["synced"] >= limit:
                break
        by_type["entity"] = stats
        total_synced += stats["synced"]
        total_tag_rows += stats["tag_rows"]

    if "todo" in wanted:
        stats = {"scanned": 0, "with_tags": 0, "synced": 0, "tag_rows": 0}
        for todo in _iter_todos(user_id):
            stats["scanned"] += 1
            tags = normalize_tags(todo.tags)
            if not tags:
                continue
            stats["with_tags"] += 1
            if not dry_run:
                tag_repo.sync_tags(user_id, "todo", todo.todo_id, tags)
            stats["synced"] += 1
            stats["tag_rows"] += len(tags)
            if limit is not None and stats["synced"] >= limit:
                break
        by_type["todo"] = stats
        total_synced += stats["synced"]
        total_tag_rows += stats["tag_rows"]

    return {
        "user_id": user_id,
        "dry_run": dry_run,
        "by_type": by_type,
        "total_synced": total_synced,
        "total_tag_rows": total_tag_rows,
    }


def _tags_of(value) -> List:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        return [value]
    return []


def _apply_mapping(tags: List, mapping: Dict[str, List[str]]):
    out, seen = [], set()
    replaced, dropped = [], []
    for tag in tags:
        if not isinstance(tag, str):
            out.append(tag)
            continue
        targets = mapping.get(tag)
        if targets is None:
            targets = [tag]
        else:
            replaced.append({"from": tag, "to": list(targets)})
        for new in targets:
            if new in seen:
                dropped.append({"from": tag, "to": new})
                continue
            seen.add(new)
            out.append(new)
    return out, replaced, dropped


def _validate_rename_args(source: str, target: str) -> List[str]:
    if not isinstance(source, str) or not source:
        raise TagRenameError("source must be a non-empty string")
    if not isinstance(target, str) or not target:
        raise TagRenameError("target must be a non-empty string")
    if source == target:
        raise TagRenameError("source and target must differ")
    canonical = normalize_tag(target)
    if canonical != target:
        raise TagRenameError(
            f"target must already be canonical (got {target!r}, expected {canonical!r})"
        )
    return [target]


def _carrier_title(entity_type: str, row) -> str:
    if entity_type == "todo":
        return row.name
    if entity_type == "note":
        return row.content_key
    if entity_type == "entity":
        return row.name
    return ""


def _load_authoring_row(session, user_id: int, entity_type: str, entity_id: str):
    if entity_type == "todo":
        return session.query(TodoEntity).filter_by(user_id=user_id, todo_id=entity_id).one_or_none()
    if entity_type == "note":
        return session.query(NoteEntity).filter(
            NoteEntity.user_id == user_id,
            NoteEntity.note_id == entity_id,
            NoteEntity.deleted_at.is_(None),
        ).one_or_none()
    if entity_type == "entity":
        return session.query(EntityEntity).filter_by(
            user_id=user_id, entity_id=entity_id
        ).one_or_none()
    return None


def _authoring_tags(entity_type: str, row) -> List:
    if entity_type == "todo":
        return _tags_of(row.tags)
    fm = row.front_matter if isinstance(row.front_matter, dict) else None
    return _tags_of(fm.get("tags") if fm else None)


def _public_projection_item(item: Dict) -> Dict:
    """Strip internal row ids before a plan crosses the host boundary."""
    out = {
        "entity_type": item["entity_type"],
        "entity_id": item["entity_id"],
        "from": item["from"],
        "to": item["to"],
    }
    return out


def compute_plan_hash(plan: Dict) -> str:
    """Stable hash over the semantic DB plan (files/blockers are CLI-local)."""
    payload = {
        "mode": plan["mode"],
        "source": plan["source"],
        "target": plan["target"],
        "carriers": sorted(
            [
                {
                    "entity_type": c["entity_type"],
                    "entity_id": c["entity_id"],
                    "tags_before": c["tags_before"],
                    "tags_after": c["tags_after"],
                    "content_key": c.get("content_key"),
                }
                for c in plan["carriers"]
            ],
            key=lambda c: (c["entity_type"], c["entity_id"]),
        ),
        "projection": {
            "updates": sorted(
                plan["projection"]["updates"],
                key=lambda i: (i["entity_type"], i["entity_id"], i["from"], i["to"]),
            ),
            "deletes": sorted(
                plan["projection"]["deletes"],
                key=lambda i: (i["entity_type"], i["entity_id"], i["from"], i["to"]),
            ),
            "inserts": sorted(
                plan["projection"]["inserts"],
                key=lambda i: (i["entity_type"], i["entity_id"], i["to"]),
            ),
        },
        "target_exists": plan["target_exists"],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build_rename_plan(session, user_id: int, source: str, target: str) -> Dict:
    targets = _validate_rename_args(source, target)
    mapping = {source: targets}

    source_pairs = (
        session.query(EntityTagEntity.entity_type, EntityTagEntity.entity_id)
        .filter_by(user_id=user_id, tag=source)
        .all()
    )
    carrier_keys = sorted({(etype, eid) for etype, eid in source_pairs})

    target_exists = (
        session.query(EntityTagEntity.id)
        .filter_by(user_id=user_id, tag=target)
        .first()
        is not None
    )
    mode = "merge" if target_exists else "rename"

    # Prefetch projection tags only for the affected carriers.
    existing_by_carrier: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    if carrier_keys:
        type_ids: Dict[str, List[str]] = defaultdict(list)
        for etype, eid in carrier_keys:
            type_ids[etype].append(eid)
        for etype, eids in type_ids.items():
            rows = (
                session.query(EntityTagEntity)
                .filter(
                    EntityTagEntity.user_id == user_id,
                    EntityTagEntity.entity_type == etype,
                    EntityTagEntity.entity_id.in_(eids),
                )
                .all()
            )
            for row in rows:
                existing_by_carrier[(row.entity_type, row.entity_id)].append(row.tag)
        for key in existing_by_carrier:
            existing_by_carrier[key] = sorted(existing_by_carrier[key])

    carriers = []
    blockers = []
    for entity_type, entity_id in carrier_keys:
        if entity_type in AUTHORING_TYPES:
            row = _load_authoring_row(session, user_id, entity_type, entity_id)
            if row is None:
                blockers.append({
                    "kind": "missing_authoring_carrier",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                })
                continue
            tags_before = _authoring_tags(entity_type, row)
            if source not in tags_before:
                blockers.append({
                    "kind": "authoring_missing_source",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "tags": tags_before,
                })
                continue
            tags_after, replaced, dropped = _apply_mapping(tags_before, mapping)
            entry = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title": _carrier_title(entity_type, row),
                "tags_before": tags_before,
                "tags_after": tags_after,
                "replaced": replaced,
                "dropped": dropped,
            }
            if entity_type == "note":
                entry["content_key"] = row.content_key
            carriers.append(entry)
        elif entity_type in DIRECT_TYPES:
            tags_before = list(existing_by_carrier[(entity_type, entity_id)])
            tags_after, replaced, dropped = _apply_mapping(tags_before, mapping)
            carriers.append({
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title": "",
                "tags_before": tags_before,
                "tags_after": tags_after,
                "replaced": replaced,
                "dropped": dropped,
            })
        else:
            blockers.append({
                "kind": "unknown_entity_type",
                "entity_type": entity_type,
                "entity_id": entity_id,
            })

    # Projection: only rewrite rows that currently hold the exact source value.
    # Carrier already has target -> delete source row; otherwise update in place.
    # inserts stay in the structure so a later 1->N split can reuse it.
    # Private ops keep the row id for the apply transaction; the public envelope
    # returned to modules never includes internal integer PKs.
    tag_rows = (
        session.query(EntityTagEntity)
        .filter_by(user_id=user_id, tag=source)
        .order_by(EntityTagEntity.entity_type, EntityTagEntity.entity_id, EntityTagEntity.id)
        .all()
    )
    existing_sets: Dict[Tuple[str, str], set] = {
        key: set(values) for key, values in existing_by_carrier.items()
    }
    for row in tag_rows:
        existing_sets.setdefault((row.entity_type, row.entity_id), set()).add(row.tag)

    private_ops = {"updates": [], "deletes": [], "inserts": []}
    for row in tag_rows:
        key = (row.entity_type, row.entity_id)
        pending = [t for t in targets if t not in existing_sets[key]]
        if not pending:
            private_ops["deletes"].append({
                "id": row.id,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "from": row.tag,
                "to": targets[0],
            })
        else:
            private_ops["updates"].append({
                "id": row.id,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "from": row.tag,
                "to": pending[0],
            })
            for extra in pending[1:]:
                private_ops["inserts"].append({
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "from": row.tag,
                    "to": extra,
                })
            existing_sets[key].update(pending)
        existing_sets[key].discard(row.tag)

    projection = {
        "updates": [_public_projection_item(i) for i in private_ops["updates"]],
        "deletes": [_public_projection_item(i) for i in private_ops["deletes"]],
        "inserts": [_public_projection_item(i) for i in private_ops["inserts"]],
    }

    files = [
        {
            "entity_type": "note",
            "entity_id": c["entity_id"],
            "content_key": c["content_key"],
            "tags_before": c["tags_before"],
            "tags_after": c["tags_after"],
        }
        for c in carriers
        if c["entity_type"] == "note" and c.get("content_key")
    ]

    plan = {
        "mode": mode,
        "source": source,
        "target": target,
        "target_exists": target_exists,
        "carriers": carriers,
        "files": files,
        "blockers": blockers,
        "projection": projection,
        "summary": {
            "carriers_total": len(carriers),
            "carriers_by_type": {
                t: sum(1 for c in carriers if c["entity_type"] == t)
                for t in sorted({c["entity_type"] for c in carriers})
            },
            "files": len(files),
            "blockers": len(blockers),
            "projection_updates": len(projection["updates"]),
            "projection_deletes": len(projection["deletes"]),
            "projection_inserts": len(projection["inserts"]),
        },
    }
    plan["plan_hash"] = compute_plan_hash(plan)
    # Transaction-private only; stripped before any host/module return.
    plan["_projection_ops"] = private_ops
    return plan


def _public_plan(plan: Dict) -> Dict:
    """Return the API/journal envelope without private transaction fields."""
    return {
        "mode": plan["mode"],
        "source": plan["source"],
        "target": plan["target"],
        "target_exists": plan["target_exists"],
        "carriers": plan["carriers"],
        "files": plan["files"],
        "blockers": plan["blockers"],
        "projection": plan["projection"],
        "summary": plan["summary"],
        "plan_hash": plan["plan_hash"],
    }


def plan_rename(user_id: int, source: str, target: str) -> Dict:
    """Compute a rename/merge plan from live entity_tag + authoring state.

    Does not mutate. Returns mode/carriers/files/blockers/plan_hash. Files are
    note content_keys only; the CLI computes the on-disk rewrite and blockers.
    """
    with get_db() as session:
        return _public_plan(_build_rename_plan(session, user_id, source, target))


def _lock_authoring_row(session, user_id: int, entity_type: str, entity_id: str):
    """Lock one authoring carrier row; map a missing row to TagRenameConflict.

    populate_existing is required because `_build_rename_plan` may already have
    the same identity in this session: a plain FOR UPDATE would return the stale
    cached object and the exact-value check would miss a concurrent commit.
    """
    from sqlalchemy.orm.exc import NoResultFound

    try:
        if entity_type == "todo":
            return (
                session.query(TodoEntity)
                .filter_by(user_id=user_id, todo_id=entity_id)
                .execution_options(populate_existing=True)
                .with_for_update()
                .one()
            )
        if entity_type == "note":
            return (
                session.query(NoteEntity)
                .filter(
                    NoteEntity.user_id == user_id,
                    NoteEntity.note_id == entity_id,
                    NoteEntity.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
                .with_for_update()
                .one()
            )
        if entity_type == "entity":
            return (
                session.query(EntityEntity)
                .filter_by(user_id=user_id, entity_id=entity_id)
                .execution_options(populate_existing=True)
                .with_for_update()
                .one()
            )
    except NoResultFound as exc:
        raise TagRenameConflict(
            f"{entity_type} {entity_id} changed since the plan was built"
        ) from exc
    raise TagRenameConflict(f"unsupported authoring type {entity_type!r}")


def _lock_projection_row(session, user_id: int, row_id: int, expected_from: str):
    """Lock one entity_tag row and assert it still holds the planned source.

    populate_existing refreshes attributes even when the row is already in this
    session's identity map from plan construction.
    """
    from sqlalchemy.orm.exc import NoResultFound

    try:
        row = (
            session.query(EntityTagEntity)
            .filter_by(id=row_id, user_id=user_id)
            .execution_options(populate_existing=True)
            .with_for_update()
            .one()
        )
    except NoResultFound as exc:
        raise TagRenameConflict(
            f"entity_tag row for {expected_from!r} changed since the plan was built"
        ) from exc
    if row.tag != expected_from:
        raise TagRenameConflict(
            f"entity_tag for {row.entity_type}/{row.entity_id} changed since the plan was built"
        )
    return row


def _verify_after_apply(session, user_id: int, plan: Dict) -> None:
    source = plan["source"]
    leftover = (
        session.query(EntityTagEntity.id)
        .filter_by(user_id=user_id, tag=source)
        .all()
    )
    if leftover:
        raise TagRenameConflict(
            f"entity_tag still has source spelling {source!r} after apply"
        )

    projected = defaultdict(set)
    carrier_keys = {(c["entity_type"], c["entity_id"]) for c in plan["carriers"]}
    if carrier_keys:
        type_ids: Dict[str, List[str]] = defaultdict(list)
        for etype, eid in carrier_keys:
            type_ids[etype].append(eid)
        for etype, eids in type_ids.items():
            for row in (
                session.query(EntityTagEntity)
                .filter(
                    EntityTagEntity.user_id == user_id,
                    EntityTagEntity.entity_type == etype,
                    EntityTagEntity.entity_id.in_(eids),
                )
                .all()
            ):
                projected[(row.entity_type, row.entity_id)].add(row.tag)

    for carrier in plan["carriers"]:
        etype, eid = carrier["entity_type"], carrier["entity_id"]
        if etype in AUTHORING_TYPES:
            row = _load_authoring_row(session, user_id, etype, eid)
            if row is None:
                raise TagRenameConflict(f"{etype} {eid} missing after apply")
            actual = _authoring_tags(etype, row)
            if actual != carrier["tags_after"]:
                raise TagRenameConflict(
                    f"{etype} {eid}: authoring tags are {actual}, expected {carrier['tags_after']}"
                )
            extras = projected[(etype, eid)] - set(carrier["tags_after"])
            if extras:
                raise TagRenameConflict(
                    f"{etype} {eid}: entity_tag has unexpected {sorted(extras)}"
                )
        missing = set(carrier["tags_after"]) - projected[(etype, eid)]
        if missing:
            raise TagRenameConflict(
                f"{etype} {eid}: entity_tag missing {sorted(missing)}"
            )


def apply_rename(
    user_id: int,
    source: str,
    target: str,
    *,
    plan_hash: str,
) -> Dict:
    """Apply a rename/merge inside one DB transaction.

    Recomputes the plan, refuses on plan_hash mismatch or live drift, locks the
    affected authoring and entity_tag rows, rewrites them, appends one
    todo.history entry per touched todo, and post-verifies. Never deletes a
    carrier or content. Also keeps tag_vocabulary coordinated with the new
    identity: registers `target`, then retires `source`'s vocabulary row once
    entity_tag no longer holds it.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm.exc import NoResultFound

    if not isinstance(plan_hash, str) or not plan_hash:
        raise TagRenameError("plan_hash is required")

    with get_db() as session:
        try:
            plan = _build_rename_plan(session, user_id, source, target)
            if plan["blockers"]:
                raise TagRenameConflict(f"rename blocked: {plan['blockers']}")
            if plan["plan_hash"] != plan_hash:
                raise TagRenameConflict(
                    "plan_hash mismatch; re-run dry-run and apply the fresh plan"
                )

            by_type = defaultdict(dict)
            for carrier in plan["carriers"]:
                by_type[carrier["entity_type"]][carrier["entity_id"]] = carrier

            now, now_unix = get_utc_iso8601_timestamp(), get_unix_timestamp()
            private_ops = plan["_projection_ops"]

            # Register the target vocabulary identity before any other pending
            # write exists in this session: ensure() may use a nested SAVEPOINT
            # (SQLite) whose flush would otherwise sweep up unrelated pending
            # authoring/entity_tag changes below and roll them back together
            # with a spurious vocabulary race.
            vocabulary_repo.ensure(session, user_id, target)

            # Lock every affected authoring + projection row before mutating so a
            # concurrent writer cannot slip a change past the exact-value check.
            for todo_id, carrier in by_type["todo"].items():
                row = _lock_authoring_row(session, user_id, "todo", todo_id)
                if _tags_of(row.tags) != carrier["tags_before"]:
                    raise TagRenameConflict(
                        f"todo {todo_id} tags changed since the plan was built"
                    )
                row.tags = list(carrier["tags_after"])
                history = list(row.history or [])
                history.append({
                    "timestamp": now,
                    "unix_timestamp": now_unix,
                    "action": "updated",
                    "note": f"changed: tags={carrier['tags_after']!r}",
                })
                row.history = history
                flag_modified(row, "history")
                flag_modified(row, "tags")

            for note_id, carrier in by_type["note"].items():
                row = _lock_authoring_row(session, user_id, "note", note_id)
                fm = dict(row.front_matter or {})
                if _tags_of(fm.get("tags")) != carrier["tags_before"]:
                    raise TagRenameConflict(
                        f"note {note_id} front matter changed since the plan was built"
                    )
                fm["tags"] = list(carrier["tags_after"])
                row.front_matter = fm
                flag_modified(row, "front_matter")

            for entity_id, carrier in by_type["entity"].items():
                row = _lock_authoring_row(session, user_id, "entity", entity_id)
                fm = dict(row.front_matter or {})
                if _tags_of(fm.get("tags")) != carrier["tags_before"]:
                    raise TagRenameConflict(
                        f"entity {entity_id} front matter changed since the plan was built"
                    )
                fm["tags"] = list(carrier["tags_after"])
                row.front_matter = fm
                flag_modified(row, "front_matter")

            for item in private_ops["deletes"]:
                row = _lock_projection_row(session, user_id, item["id"], item["from"])
                session.delete(row)
            # Flush deletes before updates/inserts so the unique constraint cannot
            # reject a carrier whose source row is being removed and re-added under
            # another spelling in the same transaction.
            session.flush()

            for item in private_ops["updates"]:
                row = _lock_projection_row(session, user_id, item["id"], item["from"])
                row.tag = item["to"]
            session.flush()

            for item in private_ops["inserts"]:
                session.add(EntityTagEntity(
                    user_id=user_id,
                    entity_type=item["entity_type"],
                    entity_id=item["entity_id"],
                    tag=item["to"],
                ))
            session.flush()

            _verify_after_apply(session, user_id, plan)

            # The source spelling is retired: entity_tag holds none of it after
            # a verified rename/merge, so its vocabulary identity should not
            # linger as a duplicate zero-use row of the tag it was just folded
            # into or renamed to.
            session.query(TagVocabularyEntity).filter_by(user_id=user_id, tag=source).delete()
        except TagRenameConflict:
            raise
        except (NoResultFound, IntegrityError) as exc:
            raise TagRenameConflict(
                "tag rename conflicted with a concurrent change; re-run dry-run"
            ) from exc

        return _public_plan(plan)
