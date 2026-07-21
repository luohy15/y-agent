"""Function-based note repository."""

from datetime import datetime, timezone
from typing import List, Optional
from storage.entity.note import NoteEntity
from storage.entity.entity_tag import EntityTagEntity
from storage.dto.note import Note
from storage.database.base import get_db
from storage.util import apply_time_filter, generate_id


def _entity_to_dto(entity: NoteEntity) -> Note:
    return Note(
        note_id=entity.note_id,
        content_key=entity.content_key,
        front_matter=entity.front_matter,
        deleted_at=entity.deleted_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def list_notes(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[Note]:
    with get_db() as session:
        query = session.query(NoteEntity).filter_by(user_id=user_id)
        if not include_deleted:
            query = query.filter(NoteEntity.deleted_at.is_(None))
        if tag:
            tagged_ids = session.query(EntityTagEntity.entity_id).filter_by(
                user_id=user_id, entity_type="note", tag=tag
            )
            query = query.filter(NoteEntity.note_id.in_(tagged_ids))
        query = apply_time_filter(query, NoteEntity.updated_at, on=on, from_=from_, to=to)
        query = apply_time_filter(query, NoteEntity.created_at, on=created_on, from_=created_from, to=created_to)
        query = apply_time_filter(query, NoteEntity.updated_at, on=updated_on, from_=updated_from, to=updated_to)
        rows = (
            query.order_by(NoteEntity.updated_at_unix.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_note(user_id: int, note_id: str, include_deleted: bool = False) -> Optional[Note]:
    with get_db() as session:
        query = session.query(NoteEntity).filter_by(user_id=user_id, note_id=note_id)
        if not include_deleted:
            query = query.filter(NoteEntity.deleted_at.is_(None))
        entity = query.first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_note_by_content_key(user_id: int, content_key: str, include_deleted: bool = False) -> Optional[Note]:
    with get_db() as session:
        query = session.query(NoteEntity).filter_by(user_id=user_id, content_key=content_key)
        if not include_deleted:
            query = query.filter(NoteEntity.deleted_at.is_(None))
        entity = query.first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_notes_by_ids(user_id: int, note_ids: List[str], include_deleted: bool = False) -> List[Note]:
    if not note_ids:
        return []
    with get_db() as session:
        query = (
            session.query(NoteEntity)
            .filter(NoteEntity.user_id == user_id, NoteEntity.note_id.in_(note_ids))
        )
        if not include_deleted:
            query = query.filter(NoteEntity.deleted_at.is_(None))
        rows = query.all()
        return [_entity_to_dto(r) for r in rows]


def save_note(user_id: int, note: Note) -> Note:
    """Upsert a note by user_id + note_id."""
    with get_db() as session:
        entity = session.query(NoteEntity).filter_by(user_id=user_id, note_id=note.note_id).first()
        if entity:
            entity.content_key = note.content_key
            if note.front_matter is not None:
                entity.front_matter = note.front_matter
            session.flush()
            return _entity_to_dto(entity)
        else:
            entity = NoteEntity(
                user_id=user_id,
                note_id=note.note_id,
                content_key=note.content_key,
                front_matter=note.front_matter,
            )
            session.add(entity)
            session.flush()
            return _entity_to_dto(entity)


def delete_note(user_id: int, note_id: str) -> bool:
    """Soft-delete: set deleted_at=now. Idempotent; returns False only if not found."""
    with get_db() as session:
        entity = session.query(NoteEntity).filter_by(user_id=user_id, note_id=note_id).first()
        if not entity:
            return False
        if entity.deleted_at is None:
            entity.deleted_at = datetime.now(timezone.utc).isoformat()
            session.flush()
        return True
