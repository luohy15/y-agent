"""Function-based tg_topic repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.tg_topic import TgTopicEntity
from storage.dto.tg_topic import TgTopic
from storage.database.base import get_db


def _entity_to_dto(entity: TgTopicEntity) -> TgTopic:
    return TgTopic(
        id=entity.id,
        group_id=entity.group_id,
        topic_id=entity.topic_id,
        topic_name=entity.topic_name,
        topic_icon=entity.topic_icon,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_topics(user_id: int, group_id: int) -> List[TgTopic]:
    with get_db() as session:
        rows = (
            session.query(TgTopicEntity)
            .filter_by(user_id=user_id, group_id=group_id)
            .order_by(TgTopicEntity.id.asc())
            .all()
        )
        return [_entity_to_dto(row) for row in rows]


def get_topic(user_id: int, topic_id: int) -> Optional[TgTopic]:
    """Get a topic config by its primary key id."""
    with get_db() as session:
        row = session.query(TgTopicEntity).filter_by(user_id=user_id, id=topic_id).first()
        if row:
            return _entity_to_dto(row)
        return None


def get_topic_by_name(user_id: int, group_id: int, topic_name: str) -> Optional[TgTopic]:
    with get_db() as session:
        row = (
            session.query(TgTopicEntity)
            .filter_by(user_id=user_id, group_id=group_id, topic_name=topic_name)
            .first()
        )
        if row:
            return _entity_to_dto(row)
        return None


def add_topic(user_id: int, group_id: int, topic_name: str, topic_icon: Optional[str] = None) -> TgTopic:
    with get_db() as session:
        entity = TgTopicEntity(
            user_id=user_id,
            group_id=group_id,
            topic_name=topic_name,
            topic_icon=topic_icon,
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def update_topic_id(user_id: int, pk_id: int, tg_topic_id: int) -> Optional[TgTopic]:
    """Set the Telegram topic_id (message_thread_id) after creation."""
    with get_db() as session:
        entity = session.query(TgTopicEntity).filter_by(user_id=user_id, id=pk_id).first()
        if not entity:
            return None
        entity.topic_id = tg_topic_id
        session.flush()
        return _entity_to_dto(entity)


def upsert_topic(user_id: int, group_id: int, topic_name: str,
                  tg_topic_id: Optional[int] = None, topic_icon: Optional[str] = None) -> TgTopic:
    """Insert or update a topic. If (user_id, group_id, topic_name) exists, update topic_id/icon."""
    with get_db() as session:
        entity = (
            session.query(TgTopicEntity)
            .filter_by(user_id=user_id, group_id=group_id, topic_name=topic_name)
            .first()
        )
        if entity:
            if tg_topic_id is not None:
                entity.topic_id = tg_topic_id
            if topic_icon is not None:
                entity.topic_icon = topic_icon
            session.flush()
        else:
            entity = TgTopicEntity(
                user_id=user_id,
                group_id=group_id,
                topic_name=topic_name,
                topic_id=tg_topic_id,
                topic_icon=topic_icon,
            )
            session.add(entity)
            session.flush()
        return _entity_to_dto(entity)


def get_topic_by_thread_id(user_id: int, group_id: int, tg_topic_id: int) -> Optional[TgTopic]:
    """Look up a topic by its Telegram message_thread_id."""
    with get_db() as session:
        row = (
            session.query(TgTopicEntity)
            .filter_by(user_id=user_id, group_id=group_id, topic_id=tg_topic_id)
            .first()
        )
        if row:
            return _entity_to_dto(row)
        return None


def find_topic_by_name(user_id: int, topic_name: str) -> Optional[TgTopic]:
    """Find a topic by user_id and topic_name (any group)."""
    with get_db() as session:
        row = (
            session.query(TgTopicEntity)
            .filter_by(user_id=user_id, topic_name=topic_name)
            .first()
        )
        if row:
            return _entity_to_dto(row)
        return None


def delete_topic(user_id: int, pk_id: int) -> bool:
    with get_db() as session:
        count = session.query(TgTopicEntity).filter_by(user_id=user_id, id=pk_id).delete()
        session.flush()
        return count > 0
