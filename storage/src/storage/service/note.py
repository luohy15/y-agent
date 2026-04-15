"""Note service."""

from typing import Dict, List, Optional
from storage.dto.note import Note
from storage.repository import note as note_repo
from storage.util import generate_id


def create_note(user_id: int, content_key: str, front_matter: Optional[Dict] = None) -> Note:
    note_id = generate_id()
    note = Note(note_id=note_id, content_key=content_key, front_matter=front_matter)
    return note_repo.save_note(user_id, note)


def update_note(user_id: int, note_id: str, content_key: Optional[str] = None, front_matter: Optional[Dict] = None) -> Optional[Note]:
    existing = note_repo.get_note(user_id, note_id)
    if not existing:
        return None
    if content_key is not None:
        existing.content_key = content_key
    if front_matter is not None:
        existing.front_matter = front_matter
    return note_repo.save_note(user_id, existing)


def import_note(user_id: int, content_key: str, front_matter: Optional[Dict] = None) -> Note:
    existing = note_repo.get_note_by_content_key(user_id, content_key)
    if existing:
        if front_matter is not None:
            existing.front_matter = front_matter
        return note_repo.save_note(user_id, existing)
    return create_note(user_id, content_key, front_matter=front_matter)


def delete_note(user_id: int, note_id: str) -> bool:
    return note_repo.delete_note(user_id, note_id)


def get_note(user_id: int, note_id: str) -> Optional[Note]:
    return note_repo.get_note(user_id, note_id)


def list_notes(user_id: int, limit: int = 50, offset: int = 0) -> List[Note]:
    return note_repo.list_notes(user_id, limit=limit, offset=offset)


def get_notes_by_ids(user_id: int, note_ids: List[str]) -> List[Note]:
    return note_repo.get_notes_by_ids(user_id, note_ids)
