"""Entity service."""

from typing import Dict, List, Optional
from storage.dto.entity import Entity
from storage.repository import entity as entity_repo
from storage.repository import entity_tag as tag_repo
from storage.util import generate_id


def create_entity(
    user_id: int,
    name: str,
    type: str,
    front_matter: Optional[Dict] = None,
) -> Entity:
    entity_id = generate_id()
    entity = Entity(
        entity_id=entity_id,
        name=name,
        type=type,
        front_matter=front_matter,
    )
    return entity_repo.save_entity(user_id, entity)


def update_entity(
    user_id: int,
    entity_id: str,
    name: Optional[str] = None,
    type: Optional[str] = None,
    front_matter: Optional[Dict] = None,
) -> Optional[Entity]:
    existing = entity_repo.get_entity(user_id, entity_id)
    if not existing:
        return None
    if name is not None:
        existing.name = name
    if type is not None:
        existing.type = type
    if front_matter is not None:
        existing.front_matter = front_matter
    entity = entity_repo.save_entity(user_id, existing)
    if front_matter is not None:
        tag_repo.sync_tags(user_id, "entity", entity.entity_id, front_matter.get("tags") or [])
    return entity


def import_entity(
    user_id: int,
    name: str,
    type: str,
    front_matter: Optional[Dict] = None,
) -> Entity:
    """Upsert entity by (name, type). If one already exists for this user, update front_matter; else create."""
    existing = entity_repo.get_entity_by_name_type(user_id, name, type)
    if existing:
        if front_matter is not None:
            existing.front_matter = front_matter
        entity = entity_repo.save_entity(user_id, existing)
    else:
        entity = create_entity(user_id, name, type, front_matter=front_matter)
    if front_matter is not None:
        tag_repo.sync_tags(user_id, "entity", entity.entity_id, front_matter.get("tags") or [])
    return entity


def delete_entity(user_id: int, entity_id: str) -> bool:
    deleted = entity_repo.delete_entity(user_id, entity_id)
    if deleted:
        tag_repo.delete_for_entity(user_id, "entity", entity_id)
    return deleted


def get_entity(user_id: int, entity_id: str) -> Optional[Entity]:
    return entity_repo.get_entity(user_id, entity_id)


def list_entities(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    type: Optional[str] = None,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[Entity]:
    return entity_repo.list_entities(
        user_id, limit=limit, offset=offset, type=type, tag=tag,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )


def get_entities_by_ids(user_id: int, entity_ids: List[str]) -> List[Entity]:
    return entity_repo.get_entities_by_ids(user_id, entity_ids)
