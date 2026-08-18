"""Function-based user_preference repository using SQLAlchemy sessions."""

from typing import Any, Optional

from storage.database.base import get_db
from storage.dto.user_preference import UserPreference
from storage.entity.user import UserEntity
from storage.entity.user_preference import UserPreferenceEntity
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


class PreferenceRevisionConflict(Exception):
    """Raised when a conditional preference PUT's base_revision doesn't match.

    Carries the current stored value (None if no row exists) so the caller can
    surface it to the client for a merge/retry, per todo 3200.
    """

    def __init__(self, user_id: int, key: str, current: Optional[UserPreference]):
        self.user_id = user_id
        self.key = key
        self.current = current
        super().__init__(f"base_revision mismatch for user_id={user_id} key={key!r}")


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


def upsert_preference(
    user_id: int,
    key: str,
    value: Any,
    base_revision: Optional[int] = None,
) -> UserPreference:
    """Create or update a preference.

    `base_revision` is None for the existing unconditional callers (last-write-
    wins, unchanged behavior). When provided, it must equal the current row's
    `updated_at_unix` (0 meaning no row exists yet); a mismatch raises
    `PreferenceRevisionConflict` with the current value so the caller can 409.
    Conditional writes lock the owning user row first so concurrent first-writes
    (no preference row yet) are serialized rather than racing on insert, and
    explicitly advance `updated_at_unix` past the prior revision so same-
    millisecond writes still produce a strictly increasing revision.
    """
    with get_db() as session:
        if base_revision is None:
            entity = session.query(UserPreferenceEntity).filter_by(user_id=user_id, key=key).first()
            if entity:
                entity.value = value
            else:
                entity = UserPreferenceEntity(user_id=user_id, key=key, value=value)
                session.add(entity)
            session.flush()
            return _entity_to_dto(entity)

        session.query(UserEntity).filter_by(id=user_id).with_for_update().first()
        entity = (
            session.query(UserPreferenceEntity)
            .filter_by(user_id=user_id, key=key)
            .with_for_update()
            .first()
        )
        current_revision = entity.updated_at_unix if entity else 0
        if current_revision != base_revision:
            current = _entity_to_dto(entity) if entity else None
            raise PreferenceRevisionConflict(user_id, key, current)

        next_unix = max(get_unix_timestamp(), current_revision + 1)
        next_iso = get_utc_iso8601_timestamp()
        if entity:
            entity.value = value
        else:
            entity = UserPreferenceEntity(user_id=user_id, key=key, value=value)
            session.add(entity)
        entity.updated_at_unix = next_unix
        entity.updated_at = next_iso
        session.flush()
        return _entity_to_dto(entity)


def delete_preference(user_id: int, key: str) -> bool:
    with get_db() as session:
        count = session.query(UserPreferenceEntity).filter_by(user_id=user_id, key=key).delete()
        session.flush()
        return count > 0
