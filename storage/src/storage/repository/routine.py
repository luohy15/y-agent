"""Function-based routine repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.routine import RoutineEntity
from storage.dto.routine import Routine
from storage.database.base import get_db


def _entity_to_dto(entity: RoutineEntity) -> Routine:
    return Routine(
        routine_id=entity.routine_id,
        name=entity.name,
        schedule=entity.schedule,
        message=entity.message,
        description=entity.description,
        target_topic=entity.target_topic,
        target_skill=entity.target_skill,
        work_dir=entity.work_dir,
        backend=entity.backend,
        enabled=bool(entity.enabled),
        last_run_at=entity.last_run_at,
        last_run_status=entity.last_run_status,
        last_chat_id=entity.last_chat_id,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_routines(
    user_id: int,
    enabled: Optional[bool] = None,
    limit: int = 50,
) -> List[Routine]:
    with get_db() as session:
        query = session.query(RoutineEntity).filter_by(user_id=user_id)
        if enabled is not None:
            query = query.filter_by(enabled=enabled)
        query = query.order_by(RoutineEntity.created_at_unix.asc())
        query = query.limit(limit)
        return [_entity_to_dto(row) for row in query.all()]


def get_routine(user_id: int, routine_id: str) -> Optional[Routine]:
    with get_db() as session:
        row = session.query(RoutineEntity).filter_by(user_id=user_id, routine_id=routine_id).first()
        return _entity_to_dto(row) if row else None


def save_routine(user_id: int, routine: Routine) -> Routine:
    with get_db() as session:
        entity = session.query(RoutineEntity).filter_by(user_id=user_id, routine_id=routine.routine_id).first()
        fields = dict(
            name=routine.name,
            description=routine.description,
            schedule=routine.schedule,
            target_topic=routine.target_topic,
            target_skill=routine.target_skill,
            message=routine.message,
            work_dir=routine.work_dir,
            backend=routine.backend,
            enabled=routine.enabled,
            last_run_at=routine.last_run_at,
            last_run_status=routine.last_run_status,
            last_chat_id=routine.last_chat_id,
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = RoutineEntity(user_id=user_id, routine_id=routine.routine_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def delete_routine(user_id: int, routine_id: str) -> bool:
    with get_db() as session:
        count = session.query(RoutineEntity).filter_by(user_id=user_id, routine_id=routine_id).delete()
        return count > 0


def list_enabled_routines() -> List[dict]:
    """Return all enabled routines across all users.

    Returns list of dicts with the routine DTO and user_id (internal). The caller
    decides which are due via croniter — schedule eval lives in the service layer
    so the repo stays free of cron logic.
    """
    with get_db() as session:
        rows = (
            session.query(RoutineEntity)
            .filter_by(enabled=True)
            .all()
        )
        return [
            {"user_id": row.user_id, "routine": _entity_to_dto(row)}
            for row in rows
        ]
