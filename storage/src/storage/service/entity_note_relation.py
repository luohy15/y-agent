"""Entity-note relation service."""

from typing import List
from storage.repository import entity_note_relation as relation_repo


def create_relation(user_id: int, entity_id: str, note_id: str) -> bool:
    return relation_repo.create_relation(user_id, entity_id, note_id)


def delete_relation(user_id: int, entity_id: str, note_id: str) -> bool:
    return relation_repo.delete_relation(user_id, entity_id, note_id)


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    return relation_repo.list_by_entity(user_id, entity_id)


def list_by_note(user_id: int, note_id: str) -> List[str]:
    return relation_repo.list_by_note(user_id, note_id)
