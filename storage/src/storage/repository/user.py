"""User repository using SQLAlchemy sessions."""

import os
from typing import List, Optional
from sqlalchemy.orm import Session
from storage.entity.user import UserEntity


def get_or_create_user(session: Session, user_id: str) -> UserEntity:
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


def get_user(session: Session, user_id: str) -> Optional[UserEntity]:
    return session.query(UserEntity).filter_by(user_id=user_id, deleted=False).first()


def list_users(session: Session) -> List[UserEntity]:
    return session.query(UserEntity).filter_by(deleted=False).all()


def get_or_create_user_by_email(session: Session, email: str, username: str) -> UserEntity:
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


def get_current_user_db_id(session: Session) -> int:
    """Resolve the configured string user_id to the integer user.id PK."""
    env_val = os.environ.get("Y_AGENT_USER_ID")
    if env_val is not None:
        return int(env_val)
    user = get_or_create_user(session, "default")
    return user.id
