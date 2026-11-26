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
    """Return the live grant a user received for a todo, or None.

    Accepts the owner's numeric todo_id or the todo's global_id.
    """
    with get_db() as session:
        row = (
            session.query(TodoShareEntity)
            .filter_by(recipient_user_id=recipient_id, todo_id=todo_id)
            .filter(TodoShareEntity.revoked_at.is_(None))
            .first()
        )
        if row is None and todo_id:
            row = (
                session.query(TodoShareEntity)
                .join(TodoEntity, _live_join())
                .filter(
                    TodoShareEntity.recipient_user_id == recipient_id,
                    TodoShareEntity.revoked_at.is_(None),
                    TodoEntity.global_id == todo_id,
                )
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
                TodoShareEntity.recipient_user_id.is_not(None),
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
    """Return one live incoming grant by share_id, then by the todo's global_id."""
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
        if row is None and share_id:
            row = (
                session.query(TodoShareEntity)
                .join(TodoEntity, _live_join())
                .filter(
                    TodoEntity.global_id == share_id,
                    TodoShareEntity.recipient_user_id == recipient_id,
                    TodoShareEntity.revoked_at.is_(None),
                    TodoEntity.status != "deleted",
                )
                .first()
            )
        return _grant(row) if row else None


# Public share links: recipient_user_id IS NULL. Every public read says so.


def get_public_by_share_id(share_id: str) -> Optional[TodoShareEntity]:
    with get_db() as session:
        return (
            session.query(TodoShareEntity)
            .filter(
                TodoShareEntity.share_id == share_id,
                TodoShareEntity.recipient_user_id.is_(None),
            )
            .first()
        )


def get_public_by_trace_id(user_id: int, trace_id: str, include_revoked: bool = False) -> Optional[TodoShareEntity]:
    with get_db() as session:
        query = session.query(TodoShareEntity).filter(
            TodoShareEntity.user_id == user_id,
            TodoShareEntity.todo_id == trace_id,
            TodoShareEntity.recipient_user_id.is_(None),
        )
        if not include_revoked:
            query = query.filter(TodoShareEntity.revoked_at.is_(None))
        return query.first()


def create_public(
    user_id: int,
    share_id: str,
    todo_id: str,
    password_hash: Optional[str] = None,
    selection=None,
) -> TodoShareEntity:
    with get_db() as session:
        entity = TodoShareEntity(
            user_id=user_id,
            todo_id=todo_id,
            recipient_user_id=None,
            share_id=share_id,
            password_hash=password_hash,
            selection=selection,
        )
        session.add(entity)
        session.flush()
        session.expunge(entity)
        return entity


def update_public_options(share_id: str, selection, password_hash: Optional[str], replace_password: bool) -> None:
    values = {"selection": selection, "revoked_at": None}
    if replace_password:
        values["password_hash"] = password_hash
    with get_db() as session:
        session.query(TodoShareEntity).filter(
            TodoShareEntity.share_id == share_id,
            TodoShareEntity.recipient_user_id.is_(None),
        ).update(values)


def set_public_revoked(share_id: str, revoked_at: Optional[str]) -> None:
    with get_db() as session:
        session.query(TodoShareEntity).filter(
            TodoShareEntity.share_id == share_id,
            TodoShareEntity.recipient_user_id.is_(None),
        ).update({"revoked_at": revoked_at})


def list_public_by_user(user_id: int) -> List[TodoShareEntity]:
    with get_db() as session:
        entities = (
            session.query(TodoShareEntity)
            .filter(
                TodoShareEntity.user_id == user_id,
                TodoShareEntity.recipient_user_id.is_(None),
                TodoShareEntity.revoked_at.is_(None),
            )
            .order_by(TodoShareEntity.id.desc())
            .all()
        )
        for entity in entities:
            session.expunge(entity)
        return entities
