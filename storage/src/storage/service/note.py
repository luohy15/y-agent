"""Note service."""

from typing import Dict, List, Optional
from storage.dto.note import Note
from storage.repository import note as note_repo
from storage.util import generate_id


def create_note(user_id: int, content: str, front_matter: Optional[Dict] = None) -> Note:
    note_id = generate_id()
    note = Note(note_id=note_id, content=content, front_matter=front_matter)
    return note_repo.save_note(user_id, note)


def update_note(user_id: int, note_id: str, content: Optional[str] = None, front_matter: Optional[Dict] = None) -> Optional[Note]:
    existing = note_repo.get_note(user_id, note_id)
    if not existing:
        return None
    if content is not None:
        existing.content = content
    if front_matter is not None:
        existing.front_matter = front_matter
    return note_repo.save_note(user_id, existing)


def delete_note(user_id: int, note_id: str) -> bool:
    return note_repo.delete_note(user_id, note_id)


def get_note(user_id: int, note_id: str) -> Optional[Note]:
    return note_repo.get_note(user_id, note_id)


def list_notes(user_id: int, limit: int = 50, offset: int = 0) -> List[Note]:
    return note_repo.list_notes(user_id, limit=limit, offset=offset)
