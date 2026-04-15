"""Note-todo relation service."""

from typing import List
from storage.repository import note_todo_relation as relation_repo


def create_relation(user_id: int, note_id: str, todo_id: str) -> bool:
    return relation_repo.create_relation(user_id, note_id, todo_id)


def delete_relation(user_id: int, note_id: str, todo_id: str) -> bool:
    return relation_repo.delete_relation(user_id, note_id, todo_id)


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    return relation_repo.list_by_todo(user_id, todo_id)


def list_by_note(user_id: int, note_id: str) -> List[str]:
    return relation_repo.list_by_note(user_id, note_id)
