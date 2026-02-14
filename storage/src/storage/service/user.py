"""User service."""

from storage.database.base import get_db
from storage.repository.user import get_current_user_db_id


def get_current_user_id() -> int:
    with get_db() as session:
        return get_current_user_db_id(session)
