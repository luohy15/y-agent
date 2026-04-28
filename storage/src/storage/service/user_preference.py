"""User preference service."""

from typing import Any, Optional

from storage.dto.user_preference import UserPreference
from storage.repository import user_preference as user_pref_repo


def get_preference(user_id: int, key: str) -> Optional[UserPreference]:
    return user_pref_repo.get_preference(user_id, key)


def upsert_preference(user_id: int, key: str, value: Any) -> UserPreference:
    return user_pref_repo.upsert_preference(user_id, key, value)


def delete_preference(user_id: int, key: str) -> bool:
    return user_pref_repo.delete_preference(user_id, key)
