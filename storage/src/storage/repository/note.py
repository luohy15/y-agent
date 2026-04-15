"""Function-based note repository."""

from typing import List, Optional
from storage.entity.note import NoteEntity
from storage.dto.note import Note
from storage.database.base import get_db
from storage.util import generate_id


def _entity_to_dto(entity: NoteEntity) -> Note:
    return Note(
        note_id=entity.note_id,
        content_key=entity.content_key,
        front_matter=entity.front_matter,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def list_notes(user_id: int, limit: int = 50, offset: int = 0) -> List[Note]:
    with get_db() as session:
        rows = (
            session.query(NoteEntity)
            .filter_by(user_id=user_id)
            .order_by(NoteEntity.updated_at_unix.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_note(user_id: int, note_id: str) -> Optional[Note]:
    with get_db() as session:
        entity = session.query(NoteEntity).filter_by(user_id=user_id, note_id=note_id).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_note_by_content_key(user_id: int, content_key: str) -> Optional[Note]:
    with get_db() as session:
        entity = session.query(NoteEntity).filter_by(user_id=user_id, content_key=content_key).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def get_notes_by_ids(user_id: int, note_ids: List[str]) -> List[Note]:
    if not note_ids:
        return []
    with get_db() as session:
        rows = (
            session.query(NoteEntity)
            .filter(NoteEntity.user_id == user_id, NoteEntity.note_id.in_(note_ids))
            .all()
        )
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
    with get_db() as session:
        entity = session.query(NoteEntity).filter_by(user_id=user_id, note_id=note_id).first()
        if not entity:
            return False
        session.delete(entity)
        return True
