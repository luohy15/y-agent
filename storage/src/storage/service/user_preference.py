"""User preference service."""

from typing import Any, Optional

from storage.dto.user_preference import UserPreference
from storage.repository import user_preference as user_pref_repo


def get_preference(user_id: int, key: str) -> Optional[UserPreference]:
    return user_pref_repo.get_preference(user_id, key)


def upsert_preference(
    user_id: int,
    key: str,
    value: Any,
    base_revision: Optional[int] = None,
) -> UserPreference:
    return user_pref_repo.upsert_preference(user_id, key, value, base_revision=base_revision)


def delete_preference(user_id: int, key: str) -> bool:
    return user_pref_repo.delete_preference(user_id, key)


LANGUAGE_KEY = "language"
LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"


def get_language(user_id: int) -> str:
    """Effective language preference; missing or invalid reads as the default.

    A stored row that a newer release does not understand must never break a
    notice, so the closed set is enforced on read as well as on write.
    """
    pref = get_preference(user_id, LANGUAGE_KEY)
    value = pref.value if pref else None
    return value if value in LANGUAGES else DEFAULT_LANGUAGE


def set_language(user_id: int, language: Optional[str]) -> str:
    """Store a language, or clear it with None/'default'; returns the effective value."""
    if language is None or language == "default":
        delete_preference(user_id, LANGUAGE_KEY)
        return DEFAULT_LANGUAGE
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(LANGUAGES)} or default")
    upsert_preference(user_id, LANGUAGE_KEY, language)
    return language
