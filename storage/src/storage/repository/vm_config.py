"""Function-based VM config repository using SQLAlchemy sessions."""

from typing import Optional
from storage.entity.vm_config import VmConfigEntity
from storage.entity.dto import VmConfig
from storage.database.base import get_db


def _entity_to_dto(entity: VmConfigEntity) -> VmConfig:
    return VmConfig(
        api_token=entity.api_token,
        vm_name=entity.vm_name,
        work_dir=entity.work_dir,
    )


def _dto_to_entity_fields(config: VmConfig) -> dict:
    return dict(
        api_token=config.api_token,
        vm_name=config.vm_name,
        work_dir=config.work_dir,
    )


def get_config(user_id: int) -> Optional[VmConfig]:
    with get_db() as session:
        row = session.query(VmConfigEntity).filter_by(user_id=user_id).first()
        if row:
            return _entity_to_dto(row)
        return None


def set_config(user_id: int, config: VmConfig) -> VmConfig:
    with get_db() as session:
        entity = session.query(VmConfigEntity).filter_by(user_id=user_id).first()
        fields = _dto_to_entity_fields(config)
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = VmConfigEntity(user_id=user_id, **fields)
            session.add(entity)
        session.flush()
        return config


def delete_config(user_id: int) -> bool:
    with get_db() as session:
        count = session.query(VmConfigEntity).filter_by(user_id=user_id).delete()
        session.flush()
        return count > 0
