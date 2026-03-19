"""Function-based dev_worktree repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.dev_worktree import DevWorktreeEntity
from storage.dto.dev_worktree import DevWorktree, DevWorktreeHistoryEntry
from storage.database.base import get_db


def _entity_to_dto(entity: DevWorktreeEntity) -> DevWorktree:
    history = entity.history or []
    return DevWorktree(
        worktree_id=entity.worktree_id,
        name=entity.name,
        project_path=entity.project_path,
        worktree_path=entity.worktree_path,
        branch=entity.branch,
        status=entity.status,
        chat_ids=entity.chat_ids,
        history=[DevWorktreeHistoryEntry.from_dict(h) for h in history],
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_worktrees(user_id: int, status: Optional[str] = None, limit: int = 50) -> List[DevWorktree]:
    with get_db() as session:
        query = session.query(DevWorktreeEntity).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        query = query.order_by(DevWorktreeEntity.updated_at.desc())
        query = query.limit(limit)
        return [_entity_to_dto(row) for row in query.all()]


def get_worktree(user_id: int, worktree_id: str) -> Optional[DevWorktree]:
    with get_db() as session:
        row = session.query(DevWorktreeEntity).filter_by(user_id=user_id, worktree_id=worktree_id).first()
        if row:
            return _entity_to_dto(row)
        return None


def get_worktree_by_name(user_id: int, name: str) -> Optional[DevWorktree]:
    with get_db() as session:
        row = session.query(DevWorktreeEntity).filter_by(user_id=user_id, name=name).first()
        if row:
            return _entity_to_dto(row)
        return None


def save_worktree(user_id: int, worktree: DevWorktree) -> DevWorktree:
    with get_db() as session:
        entity = session.query(DevWorktreeEntity).filter_by(user_id=user_id, worktree_id=worktree.worktree_id).first()
        fields = dict(
            name=worktree.name,
            project_path=worktree.project_path,
            worktree_path=worktree.worktree_path,
            branch=worktree.branch,
            status=worktree.status,
            chat_ids=worktree.chat_ids,
            history=[h.to_dict() for h in (worktree.history or [])],
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = DevWorktreeEntity(user_id=user_id, worktree_id=worktree.worktree_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def delete_worktree(user_id: int, worktree_id: str) -> bool:
    with get_db() as session:
        count = session.query(DevWorktreeEntity).filter_by(user_id=user_id, worktree_id=worktree_id).delete()
        session.flush()
        return count > 0
