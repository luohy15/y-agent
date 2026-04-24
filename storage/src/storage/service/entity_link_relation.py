"""Entity-link relation service."""

from typing import List
from storage.repository import entity_link_relation as relation_repo


def create_relation(user_id: int, entity_id: str, activity_id: str) -> bool:
    return relation_repo.create_relation(user_id, entity_id, activity_id)


def delete_relation(user_id: int, entity_id: str, activity_id: str) -> bool:
    return relation_repo.delete_relation(user_id, entity_id, activity_id)


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    return relation_repo.list_by_entity(user_id, entity_id)


def list_by_activity(user_id: int, activity_id: str) -> List[str]:
    return relation_repo.list_by_activity(user_id, activity_id)
