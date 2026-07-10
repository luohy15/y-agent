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
        backend=entity.backend,
        model=entity.model,
        description=entity.description,
        openrouter_config=entity.openrouter_config,
        prompts=entity.prompts,
        max_tokens=entity.max_tokens,
        custom_api_path=entity.custom_api_path,
        tier=entity.tier,
        type=entity.type,
        route_weight=entity.route_weight,
        enabled=entity.enabled if entity.enabled is not None else True,
        ref_bot_name=entity.ref_bot_name,
    )


def _dto_to_entity_fields(config: BotConfig) -> dict:
    fields = dict(
        base_url=config.base_url,
        api_key=config.api_key,
        api_type=None,
        backend=config.backend,
        model=config.model,
        description=config.description,
        openrouter_config=config.openrouter_config,
        prompts=config.prompts,
        max_tokens=config.max_tokens,
        custom_api_path=config.custom_api_path,
        tier=config.tier,
        type=config.type,
        route_weight=config.route_weight,
        enabled=config.enabled,
        ref_bot_name=config.ref_bot_name,
    )
    return fields


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


def rename_config(user_id: int, old_name: str, new_name: str) -> bool:
    """Rename a bot config's name, cascading to other bot_config rows that
    point at it via `ref_bot_name`. Does not touch `chat.bot_name` (see
    `storage.repository.chat.rename_bot_name` for that cascade) or the pi
    provider sync (see `agent.pi_models.sync_pi_models`).

    Returns False if `old_name` doesn't exist, `new_name` is already taken,
    or `old_name` is the magic "default" bot name.
    """
    if old_name == "default":
        return False
    with get_db() as session:
        entity = session.query(BotConfigEntity).filter_by(user_id=user_id, name=old_name).first()
        if not entity:
            return False
        collision = session.query(BotConfigEntity).filter_by(user_id=user_id, name=new_name).first()
        if collision:
            return False
        entity.name = new_name
        session.query(BotConfigEntity).filter_by(user_id=user_id, ref_bot_name=old_name).update(
            {"ref_bot_name": new_name}
        )
        session.flush()
        return True
