"""User repository using SQLAlchemy sessions."""

from typing import List, Optional

from sqlalchemy import func

from storage.entity.user import UserEntity
from storage.database.base import get_db

def get_or_create_user(user_id: str) -> UserEntity:
    with get_db() as session:
        user = session.query(UserEntity).filter_by(user_id=user_id, deleted=False).first()
        if not user:
            parsed = UserEntity.parse_user_id(user_id)
            user = UserEntity(
                user_id=user_id,
                username=parsed['username'],
                email=parsed['email'],
            )
            session.add(user)
            session.flush()
        return user


def get_user_by_id(id: int) -> Optional[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(id=id, deleted=False).first()


def get_user_by_user_id(user_id: str) -> Optional[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(user_id=user_id, deleted=False).first()


def list_users() -> List[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(deleted=False).all()


def get_user_by_telegram_id(telegram_id: int) -> Optional[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(telegram_id=telegram_id, deleted=False).first()


def bind_telegram_id(email: str, telegram_id: int) -> Optional[UserEntity]:
    normalized = (email or "").strip().lower()
    with get_db() as session:
        user = (
            session.query(UserEntity)
            .filter(UserEntity.deleted.is_(False))
            .filter(func.lower(UserEntity.email) == normalized)
            .order_by(UserEntity.id.asc())
            .first()
        )
        if not user:
            return None
        user.telegram_id = telegram_id
        session.flush()
        return user


def unbind_telegram_id(telegram_id: int) -> Optional[UserEntity]:
    with get_db() as session:
        user = session.query(UserEntity).filter_by(telegram_id=telegram_id, deleted=False).first()
        if not user:
            return None
        user.telegram_id = None
        session.flush()
        return user


def get_user_by_email(email: str) -> Optional[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(email=email, deleted=False).first()


def get_user_by_normalized_email(email: str) -> Optional[UserEntity]:
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    with get_db() as session:
        return (
            session.query(UserEntity)
            .filter(UserEntity.deleted.is_(False))
            .filter(func.lower(UserEntity.email) == normalized)
            .order_by(UserEntity.id.asc())
            .first()
        )


def get_or_create_user_by_email(email: str, username: str) -> UserEntity:
    """Find by normalized email. Create only when no live row matches.

    An existing row is returned unchanged, including its stored email case.
    """
    normalized = (email or "").strip().lower()
    with get_db() as session:
        user = (
            session.query(UserEntity)
            .filter(UserEntity.deleted.is_(False))
            .filter(func.lower(UserEntity.email) == normalized)
            .order_by(UserEntity.id.asc())
            .first()
        )
        if not user:
            user = UserEntity(
                user_id=normalized,
                username=username,
                email=normalized,
            )
            session.add(user)
            session.flush()
        return user
