"""Tag service — cross-entity tag projection and lookup.

sync_tags() is the shared projection helper carrier slices (note/entity/todo
authoring surfaces, and the 7 direct entity_tag carriers) call to keep
entity_tag in sync with their own tag source of truth.

Phase-2 carrier modules register their hydration resolvers via
register_resolver() from their own service module (do not edit the built-in
_RESOLVERS dict from parallel batches). get_by_tag() lazy-imports
storage.service.<entity_type> by convention so self-registration runs even
when only the tag CLI/API was loaded.
"""

import importlib
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from storage.repository import entity_tag as tag_repo
from storage.service import entity as entity_service
from storage.service import note as note_service
from storage.service import todo as todo_service

# (user_id, entity_id) -> {"id": public_id, "title": display} | None
Resolver = Callable[[int, str], Optional[Dict]]


def sync_tags(user_id: int, entity_type: str, entity_id: str, tags: List[str]) -> None:
    """Reconcile the entity_tag projection for one (entity_type, entity_id) to `tags`."""
    tag_repo.sync_tags(user_id, entity_type, entity_id, tags)


def add_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    return tag_repo.add_tag(user_id, entity_type, entity_id, tag)


def remove_tag(user_id: int, entity_type: str, entity_id: str, tag: str) -> bool:
    return tag_repo.remove_tag(user_id, entity_type, entity_id, tag)


def list_tags(user_id: int, entity_type: str, entity_id: str) -> List[str]:
    return tag_repo.list_tags(user_id, entity_type, entity_id)


def delete_for_entity(user_id: int, entity_type: str, entity_id: str) -> int:
    return tag_repo.delete_for_entity(user_id, entity_type, entity_id)


def _resolve_todo(user_id: int, entity_id: str) -> Optional[Dict]:
    todo = todo_service.get_todo(user_id, entity_id)
    return {"id": todo.todo_id, "title": todo.name} if todo else None


def _resolve_note(user_id: int, entity_id: str) -> Optional[Dict]:
    note = note_service.get_note(user_id, entity_id)
    return {"id": note.note_id, "title": note.content_key} if note else None


def _resolve_entity(user_id: int, entity_id: str) -> Optional[Dict]:
    entity = entity_service.get_entity(user_id, entity_id)
    return {"id": entity.entity_id, "title": entity.name} if entity else None


# Built-in resolvers for the three existing authoring-surface carriers (S0).
# Phase-2 carriers register via register_resolver() from their own modules.
_RESOLVERS: Dict[str, Resolver] = {
    "todo": _resolve_todo,
    "note": _resolve_note,
    "entity": _resolve_entity,
}


def register_resolver(entity_type: str, resolver: Resolver) -> None:
    """Register a hydration resolver for an entity_type (idempotent overwrite).

    Call from the carrier's own service module at import time so parallel
    phase-2 batches never need to edit this file's resolver dict.
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
    registered resolver fall back to {"id": entity_id}.
    """
    pairs = tag_repo.find_by_tag(user_id, tag, prefix=prefix)
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entity_type, entity_id in pairs:
        resolver = _get_resolver(entity_type)
        item = resolver(user_id, entity_id) if resolver else None
        grouped[entity_type].append(item if item is not None else {"id": entity_id})
    return dict(grouped)


def list_vocabulary(user_id: int) -> List[Tuple[str, int]]:
    """Distinct tags for the user with usage counts."""
    return tag_repo.distinct_tags(user_id)


# Authoring-surface carriers that predate entity_tag and need a one-shot backfill.
_BACKFILL_TYPES = ("note", "entity", "todo")
_PAGE_SIZE = 200


def _normalize_tags(raw) -> List[str]:
    """Coerce front_matter.tags / todo.tags into a clean string list."""
    if not raw:
        return []
    if isinstance(raw, str):
        t = raw.strip()
        return [t] if t else []
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append(t)
        return out
    return []


def _tags_from_front_matter(front_matter: Optional[Dict]) -> List[str]:
    if not isinstance(front_matter, dict):
        return []
    return _normalize_tags(front_matter.get("tags"))


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
    Scoped to one user. The 7 direct carriers had no prior tags.
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
            tags = _normalize_tags(todo.tags)
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
