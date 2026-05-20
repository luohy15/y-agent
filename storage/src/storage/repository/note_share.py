from typing import List, Optional

from storage.database.base import get_db
from storage.entity.note_share import NoteShareEntity


def get_by_share_id(share_id: str) -> Optional[NoteShareEntity]:
    with get_db() as session:
        return session.query(NoteShareEntity).filter_by(share_id=share_id).first()


def get_by_note_id(user_id: int, note_id: str) -> Optional[NoteShareEntity]:
    with get_db() as session:
        return session.query(NoteShareEntity).filter_by(user_id=user_id, note_id=note_id).first()


def create(user_id: int, share_id: str, note_id: str, password_hash: Optional[str] = None) -> NoteShareEntity:
    with get_db() as session:
        entity = NoteShareEntity(
            user_id=user_id,
            share_id=share_id,
            note_id=note_id,
            password_hash=password_hash,
        )
        session.add(entity)
        session.flush()
        session.expunge(entity)
        return entity


def set_password_hash(share_id: str, password_hash: Optional[str]) -> None:
    with get_db() as session:
        session.query(NoteShareEntity).filter_by(share_id=share_id).update(
            {"password_hash": password_hash}
        )


def delete_by_share_id(share_id: str) -> int:
    with get_db() as session:
        return session.query(NoteShareEntity).filter_by(share_id=share_id).delete()


def list_by_user(user_id: int) -> List[NoteShareEntity]:
    with get_db() as session:
        entities = session.query(NoteShareEntity).filter_by(user_id=user_id).order_by(NoteShareEntity.id.desc()).all()
        for entity in entities:
            session.expunge(entity)
        return entities
