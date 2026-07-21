"""Tag service — cross-entity tag projection and lookup.

sync_tags() is the shared projection helper carrier slices (note/entity/todo
authoring surfaces, and the 7 direct entity_tag carriers) call to keep
entity_tag in sync with their own tag source of truth.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from storage.repository import entity_tag as tag_repo
from storage.service import entity as entity_service
from storage.service import note as note_service
from storage.service import todo as todo_service


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


# Extension point: phase-2 carrier slices (chat/calendar_event/reminder/routine/
# link/email/rss_feed) register their own resolver here when they add tag support.
_RESOLVERS = {
    "todo": _resolve_todo,
    "note": _resolve_note,
    "entity": _resolve_entity,
}


def get_by_tag(user_id: int, tag: str, prefix: bool = False) -> Dict[str, List[Dict]]:
    """Find everything tagged `tag`, grouped by entity_type and hydrated through
    each type's own service (public id + display title). entity_types without a
    registered resolver fall back to {"id": entity_id}.
    """
    pairs = tag_repo.find_by_tag(user_id, tag, prefix=prefix)
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for entity_type, entity_id in pairs:
        resolver = _RESOLVERS.get(entity_type)
        item = resolver(user_id, entity_id) if resolver else None
        grouped[entity_type].append(item if item is not None else {"id": entity_id})
    return dict(grouped)


def list_vocabulary(user_id: int) -> List[Tuple[str, int]]:
    """Distinct tags for the user with usage counts."""
    return tag_repo.distinct_tags(user_id)
