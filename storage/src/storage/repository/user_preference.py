"""Function-based user_preference repository using SQLAlchemy sessions."""

from typing import Any, Optional

from storage.database.base import get_db
from storage.dto.user_preference import UserPreference
from storage.entity.user_preference import UserPreferenceEntity


def _entity_to_dto(entity: UserPreferenceEntity) -> UserPreference:
    return UserPreference(
        key=entity.key,
        value=entity.value,
        updated_at=entity.updated_at,
        updated_at_unix=entity.updated_at_unix,
    )


def get_preference(user_id: int, key: str) -> Optional[UserPreference]:
    with get_db() as session:
        row = session.query(UserPreferenceEntity).filter_by(user_id=user_id, key=key).first()
        return _entity_to_dto(row) if row else None


def upsert_preference(user_id: int, key: str, value: Any) -> UserPreference:
    with get_db() as session:
        entity = session.query(UserPreferenceEntity).filter_by(user_id=user_id, key=key).first()
        if entity:
            entity.value = value
        else:
            entity = UserPreferenceEntity(user_id=user_id, key=key, value=value)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def delete_preference(user_id: int, key: str) -> bool:
    with get_db() as session:
        count = session.query(UserPreferenceEntity).filter_by(user_id=user_id, key=key).delete()
        session.flush()
        return count > 0
