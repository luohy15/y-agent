from typing import Dict, List

from sqlalchemy import and_

from storage.database.base import get_db
from storage.entity.todo import TodoEntity
from storage.entity.todo_share import TodoShareEntity
from storage.entity.todo_visit import TodoVisitEntity
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp

KEEP = 200


def record(user_id: int, share_id: str) -> None:
    now = get_utc_iso8601_timestamp()
    unix = get_unix_timestamp()
    with get_db() as session:
        row = session.query(TodoVisitEntity).filter_by(user_id=user_id, share_id=share_id).first()
        if row is None:
            row = TodoVisitEntity(user_id=user_id, share_id=share_id)
            session.add(row)
            session.flush()
        row.updated_at = now
        row.updated_at_unix = unix
        session.flush()
        ids = [
            item[0]
            for item in session.query(TodoVisitEntity.id)
            .filter_by(user_id=user_id)
            .order_by(TodoVisitEntity.updated_at_unix.desc(), TodoVisitEntity.id.desc())
            .all()
        ]
        extra = ids[KEEP:]
        if extra:
            session.query(TodoVisitEntity).filter(TodoVisitEntity.id.in_(extra)).delete(synchronize_session=False)


def list_live(user_id: int) -> List[Dict]:
    with get_db() as session:
        rows = (
            session.query(TodoVisitEntity, TodoShareEntity)
            .join(TodoShareEntity, TodoShareEntity.share_id == TodoVisitEntity.share_id)
            .join(
                TodoEntity,
                and_(
                    TodoEntity.user_id == TodoShareEntity.user_id,
                    TodoEntity.todo_id == TodoShareEntity.todo_id,
                ),
            )
            .filter(
                TodoVisitEntity.user_id == user_id,
                TodoShareEntity.recipient_user_id.is_(None),
                TodoShareEntity.revoked_at.is_(None),
                TodoEntity.status != "deleted",
            )
            .order_by(TodoVisitEntity.updated_at_unix.desc(), TodoVisitEntity.id.desc())
            .limit(KEEP)
            .all()
        )
        return [
            {
                "share_id": visit.share_id,
                "owner_id": share.user_id,
                "todo_id": share.todo_id,
                "visited_at": visit.updated_at,
            }
            for visit, share in rows
        ]
