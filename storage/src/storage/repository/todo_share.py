from typing import Dict, List, Optional

from sqlalchemy import and_

from storage.database.base import get_db
from storage.entity.todo import TodoEntity
from storage.entity.todo_share import TodoShareEntity, TodoShareItemEntity
from storage.util import generate_id, get_unix_timestamp, get_utc_iso8601_timestamp


def _grant(row: TodoShareEntity) -> Dict:
    return {
        "share_id": row.share_id,
        "owner_id": row.user_id,
        "todo_id": row.todo_id,
        "recipient_id": row.recipient_user_id,
        "shared_at": row.updated_at,
        "revoked_at": row.revoked_at,
    }


def _items(rows: List[TodoShareItemEntity]) -> List[Dict]:
    return [
        {"kind": row.kind, "ref_id": row.ref_id, "snapshot_key": row.snapshot_key}
        for row in rows
    ]


def get_pair(
    owner_id: int,
    todo_id: str,
    recipient_id: int,
    include_revoked: bool = False,
) -> Optional[Dict]:
    with get_db() as session:
        query = session.query(TodoShareEntity).filter_by(
            user_id=owner_id,
            todo_id=todo_id,
            recipient_user_id=recipient_id,
        )
        if not include_revoked:
            query = query.filter(TodoShareEntity.revoked_at.is_(None))
        row = query.first()
        return _grant(row) if row else None


def find_live_incoming(recipient_id: int, todo_id: str) -> Optional[Dict]:
    """Return the live grant a user received for a todo, or None."""
    with get_db() as session:
        row = (
            session.query(TodoShareEntity)
            .filter_by(recipient_user_id=recipient_id, todo_id=todo_id)
            .filter(TodoShareEntity.revoked_at.is_(None))
            .first()
        )
        return _grant(row) if row else None


def list_items(share_id: str) -> List[Dict]:
    grouped = list_items_for([share_id])
    return grouped.get(share_id, [])


def list_items_for(share_ids: List[str]) -> Dict[str, List[Dict]]:
    if not share_ids:
        return {}
    with get_db() as session:
        rows = (
            session.query(TodoShareItemEntity)
            .filter(TodoShareItemEntity.share_id.in_(share_ids))
            .order_by(TodoShareItemEntity.id.asc())
            .all()
        )
        grouped: Dict[str, List[Dict]] = {}
        for row in rows:
            grouped.setdefault(row.share_id, []).append({
                "kind": row.kind,
                "ref_id": row.ref_id,
                "snapshot_key": row.snapshot_key,
            })
        return grouped


def save_grant(owner_id: int, todo_id: str, recipient_id: int, share_id: str, items: List[Dict]) -> Dict:
    """Revive or create the grant and replace its items in one transaction."""
    now = get_utc_iso8601_timestamp()
    unix = get_unix_timestamp()
    with get_db() as session:
        row = session.query(TodoShareEntity).filter_by(
            user_id=owner_id,
            todo_id=todo_id,
            recipient_user_id=recipient_id,
        ).first()
        if row is None:
            row = TodoShareEntity(
                user_id=owner_id,
                todo_id=todo_id,
                recipient_user_id=recipient_id,
                share_id=share_id or generate_id(),
            )
            session.add(row)
            session.flush()
        elif share_id and row.share_id != share_id:
            raise ValueError("todo share id mismatch")
        stored_id = row.share_id
        previous = (
            session.query(TodoShareItemEntity)
            .filter_by(share_id=stored_id)
            .all()
        )
        old_keys = {item.snapshot_key for item in previous if item.snapshot_key}
        session.query(TodoShareItemEntity).filter_by(share_id=stored_id).delete(synchronize_session=False)
        new_keys = set()
        for item in items:
            key = item.get("snapshot_key")
            if key:
                new_keys.add(key)
            session.add(TodoShareItemEntity(
                share_id=stored_id,
                kind=item["kind"],
                ref_id=item["ref_id"],
                snapshot_key=key,
            ))
        row.revoked_at = None
        row.updated_at = now
        row.updated_at_unix = unix
        session.flush()
        return {
            "share_id": stored_id,
            "shared_at": now,
            "items": _items(
                session.query(TodoShareItemEntity).filter_by(share_id=stored_id).order_by(TodoShareItemEntity.id.asc()).all()
            ),
            "obsolete_keys": sorted(old_keys - new_keys),
        }


def revoke(owner_id: int, todo_id: str, recipient_id: int) -> Optional[Dict]:
    now = get_utc_iso8601_timestamp()
    unix = get_unix_timestamp()
    with get_db() as session:
        row = session.query(TodoShareEntity).filter_by(
            user_id=owner_id,
            todo_id=todo_id,
            recipient_user_id=recipient_id,
        ).filter(TodoShareEntity.revoked_at.is_(None)).first()
        if row is None:
            return None
        keys = [
            item.snapshot_key
            for item in session.query(TodoShareItemEntity).filter_by(share_id=row.share_id).all()
            if item.snapshot_key
        ]
        row.revoked_at = now
        row.updated_at = now
        row.updated_at_unix = unix
        return {"share_id": row.share_id, "snapshot_keys": keys}


def _live_join():
    return and_(
        TodoEntity.user_id == TodoShareEntity.user_id,
        TodoEntity.todo_id == TodoShareEntity.todo_id,
    )


def list_outgoing(owner_id: int) -> List[Dict]:
    with get_db() as session:
        rows = (
            session.query(TodoShareEntity)
            .join(TodoEntity, _live_join())
            .filter(
                TodoShareEntity.user_id == owner_id,
                TodoShareEntity.revoked_at.is_(None),
                TodoEntity.status != "deleted",
            )
            .order_by(TodoShareEntity.updated_at_unix.desc(), TodoShareEntity.id.desc())
            .all()
        )
        return [_grant(row) for row in rows]


def list_incoming(recipient_id: int) -> List[Dict]:
    with get_db() as session:
        rows = (
            session.query(TodoShareEntity)
            .join(TodoEntity, _live_join())
            .filter(
                TodoShareEntity.recipient_user_id == recipient_id,
                TodoShareEntity.revoked_at.is_(None),
                TodoEntity.status != "deleted",
            )
            .order_by(TodoShareEntity.updated_at_unix.desc(), TodoShareEntity.id.desc())
            .all()
        )
        return [_grant(row) for row in rows]


def find_live_incoming_item(recipient_id: int, kind: str, ref_id: str) -> Optional[Dict]:
    """Return the newest live grant item a user received for one ref, or None."""
    with get_db() as session:
        row = (
            session.query(TodoShareEntity, TodoShareItemEntity)
            .join(
                TodoShareItemEntity,
                TodoShareItemEntity.share_id == TodoShareEntity.share_id,
            )
            .join(TodoEntity, _live_join())
            .filter(
                TodoShareEntity.recipient_user_id == recipient_id,
                TodoShareEntity.revoked_at.is_(None),
                TodoEntity.status != "deleted",
                TodoShareItemEntity.kind == kind,
                TodoShareItemEntity.ref_id == ref_id,
            )
            .order_by(TodoShareEntity.updated_at_unix.desc(), TodoShareEntity.id.desc())
            .first()
        )
        if row is None:
            return None
        grant, item = row
        return {
            **_grant(grant),
            "kind": item.kind,
            "ref_id": item.ref_id,
            "snapshot_key": item.snapshot_key,
        }


def get_visible_incoming(recipient_id: int, share_id: str) -> Optional[Dict]:
    with get_db() as session:
        row = (
            session.query(TodoShareEntity)
            .join(TodoEntity, _live_join())
            .filter(
                TodoShareEntity.share_id == share_id,
                TodoShareEntity.recipient_user_id == recipient_id,
                TodoShareEntity.revoked_at.is_(None),
                TodoEntity.status != "deleted",
            )
            .first()
        )
        return _grant(row) if row else None
