"""Link-todo relation service."""

from typing import List
from storage.repository import link_todo_relation as relation_repo
from storage.repository import todo as todo_repo


def _canonical_todo_id(user_id: int, todo_id: str) -> str:
    """Resolve an owner todo_id or global_id to the stored numeric todo_id."""
    todo = todo_repo.get_todo(user_id, todo_id)
    return todo.todo_id if todo is not None else todo_id


def create_relation(user_id: int, activity_id: str, todo_id: str) -> bool:
    return relation_repo.create_relation(user_id, activity_id, _canonical_todo_id(user_id, todo_id))


def batch_create_relations(user_id: int, activity_ids: List[str], todo_id: str) -> int:
    return relation_repo.batch_create_relations(
        user_id, activity_ids, _canonical_todo_id(user_id, todo_id)
    )


def delete_relation(user_id: int, activity_id: str, todo_id: str) -> bool:
    return relation_repo.delete_relation(user_id, activity_id, _canonical_todo_id(user_id, todo_id))


def list_by_todo(user_id: int, todo_id: str) -> List[str]:
    return relation_repo.list_by_todo(user_id, _canonical_todo_id(user_id, todo_id))


def list_by_activity(user_id: int, activity_id: str) -> List[str]:
    return relation_repo.list_by_activity(user_id, activity_id)
