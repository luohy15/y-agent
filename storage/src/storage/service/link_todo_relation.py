"""Link-todo relation service."""

from typing import List
from storage.repository import link_todo_relation as relation_repo


def create_relation(user_id: int, link_id: str, todo_id: str) -> bool:
    return relation_repo.create_relation(user_id, link_id, todo_id)


def delete_relation(user_id: int, link_id: str, todo_id: str) -> bool:
    return relation_repo.delete_relation(user_id, link_id, todo_id)


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    return relation_repo.list_by_todo(user_id, todo_id)


def list_by_link(user_id: int, link_id: str) -> List[str]:
    return relation_repo.list_by_link(user_id, link_id)
