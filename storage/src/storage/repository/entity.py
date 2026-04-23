"""Function-based entity repository."""

from typing import List, Optional
from storage.entity.entity import EntityEntity
from storage.dto.entity import Entity
from storage.database.base import get_db


def _entity_to_dto(row: EntityEntity) -> Entity:
    return Entity(
        entity_id=row.entity_id,
        name=row.name,
        type=row.type,
        front_matter=row.front_matter,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_at_unix=row.created_at_unix,
        updated_at_unix=row.updated_at_unix,
    )


def list_entities(user_id: int, limit: int = 50, offset: int = 0, type: Optional[str] = None) -> List[Entity]:
    with get_db() as session:
        q = session.query(EntityEntity).filter_by(user_id=user_id)
        if type:
            q = q.filter_by(type=type)
        rows = (
            q.order_by(EntityEntity.updated_at_unix.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_entity(user_id: int, entity_id: str) -> Optional[Entity]:
    with get_db() as session:
        row = session.query(EntityEntity).filter_by(user_id=user_id, entity_id=entity_id).first()
        if not row:
            return None
        return _entity_to_dto(row)


def get_entity_by_name_type(user_id: int, name: str, type: str) -> Optional[Entity]:
    with get_db() as session:
        row = session.query(EntityEntity).filter_by(user_id=user_id, name=name, type=type).first()
        if not row:
            return None
        return _entity_to_dto(row)


def get_entities_by_ids(user_id: int, entity_ids: List[str]) -> List[Entity]:
    if not entity_ids:
        return []
    with get_db() as session:
        rows = (
            session.query(EntityEntity)
            .filter(EntityEntity.user_id == user_id, EntityEntity.entity_id.in_(entity_ids))
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def save_entity(user_id: int, entity: Entity) -> Entity:
    """Upsert an entity by user_id + entity_id."""
    with get_db() as session:
        row = session.query(EntityEntity).filter_by(user_id=user_id, entity_id=entity.entity_id).first()
        if row:
            row.name = entity.name
            row.type = entity.type
            if entity.front_matter is not None:
                row.front_matter = entity.front_matter
            session.flush()
            return _entity_to_dto(row)
        else:
            row = EntityEntity(
                user_id=user_id,
                entity_id=entity.entity_id,
                name=entity.name,
                type=entity.type,
                front_matter=entity.front_matter,
            )
            session.add(row)
            session.flush()
            return _entity_to_dto(row)


def delete_entity(user_id: int, entity_id: str) -> bool:
    with get_db() as session:
        row = session.query(EntityEntity).filter_by(user_id=user_id, entity_id=entity_id).first()
        if not row:
            return False
        session.delete(row)
        return True
