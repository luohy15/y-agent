"""Function-based bot config repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.bot_config import BotConfigEntity
from storage.entity.dto import BotConfig
from storage.database.base import get_db


def _entity_to_dto(entity: BotConfigEntity) -> BotConfig:
    return BotConfig(
        name=entity.name,
        base_url=entity.base_url,
        api_key=entity.api_key,
        api_type=entity.api_type,
        model=entity.model,
        description=entity.description,
        openrouter_config=entity.openrouter_config,
        prompts=entity.prompts,
        max_tokens=entity.max_tokens,
        custom_api_path=entity.custom_api_path,
    )


def _dto_to_entity_fields(config: BotConfig) -> dict:
    return dict(
        base_url=config.base_url,
        api_key=config.api_key,
        api_type=config.api_type,
        model=config.model,
        description=config.description,
        openrouter_config=config.openrouter_config,
        prompts=config.prompts,
        max_tokens=config.max_tokens,
        custom_api_path=config.custom_api_path,
    )


def list_configs(user_id: int) -> List[BotConfig]:
    with get_db() as session:
        rows = session.query(BotConfigEntity).filter_by(user_id=user_id).all()
        return [_entity_to_dto(row) for row in rows]


def get_config(user_id: int, name: str = "default") -> Optional[BotConfig]:
    with get_db() as session:
        row = session.query(BotConfigEntity).filter_by(user_id=user_id, name=name).first()
        if row:
            return _entity_to_dto(row)
        return None


def add_config(user_id: int, config: BotConfig) -> BotConfig:
    with get_db() as session:
        entity = session.query(BotConfigEntity).filter_by(user_id=user_id, name=config.name).first()
        fields = _dto_to_entity_fields(config)
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = BotConfigEntity(user_id=user_id, name=config.name, **fields)
            session.add(entity)
        session.flush()
        return config


def delete_config(user_id: int, name: str) -> bool:
    with get_db() as session:
        count = session.query(BotConfigEntity).filter_by(user_id=user_id, name=name).delete()
        session.flush()
        return count > 0
