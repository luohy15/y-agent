"""User repository using SQLAlchemy sessions."""

from typing import List, Optional
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


def get_user(user_id: str) -> Optional[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(user_id=user_id, deleted=False).first()


def list_users() -> List[UserEntity]:
    with get_db() as session:
        return session.query(UserEntity).filter_by(deleted=False).all()


def get_or_create_user_by_email(email: str, username: str) -> UserEntity:
    with get_db() as session:
        user = session.query(UserEntity).filter_by(email=email, deleted=False).first()
        if not user:
            user = UserEntity(
                user_id=email,
                username=username,
                email=email,
            )
            session.add(user)
            session.flush()
        return user
