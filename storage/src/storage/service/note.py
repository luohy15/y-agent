"""Note service."""

from typing import Any, Dict, List, Optional
from storage.dto.note import Note
from storage.repository import note as note_repo
from storage.repository import note_todo_relation as note_todo_repo
from storage.repository import entity_note_relation as entity_note_repo
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


def delete_note(user_id: int, note_id: str, force: bool = False) -> Dict[str, Any]:
    """Soft-delete a note.

    Returns a structured result dict:
      {ok: True, deleted: bool}                       # success (deleted=False if already deleted / not found)
      {ok: False, reason: str, todo_relations: int, entity_relations: int}  # refused

    Safety: refuses if any relations exist. With force=True, auto-cleans
    note_todo_relation rows but still refuses if entity_note_relation has any
    rows (entity backing notes are sacrosanct; user must delete entity first).
    """
    existing = note_repo.get_note(user_id, note_id, include_deleted=True)
    if not existing:
        return {"ok": True, "deleted": False}

    todo_ids = note_todo_repo.list_by_note(user_id, note_id)
    entity_ids = entity_note_repo.list_by_note(user_id, note_id)

    if entity_ids:
        return {
            "ok": False,
            "reason": "note backs one or more entities; delete the entity first",
            "todo_relations": len(todo_ids),
            "entity_relations": len(entity_ids),
        }

    if todo_ids and not force:
        return {
            "ok": False,
            "reason": "note is linked to one or more todos; rerun with force=true to unlink and delete",
            "todo_relations": len(todo_ids),
            "entity_relations": 0,
        }

    if todo_ids and force:
        for todo_id in todo_ids:
            note_todo_repo.delete_relation(user_id, note_id, todo_id)

    deleted = note_repo.delete_note(user_id, note_id)
    return {"ok": True, "deleted": deleted}


def get_note(user_id: int, note_id: str, include_deleted: bool = False) -> Optional[Note]:
    return note_repo.get_note(user_id, note_id, include_deleted=include_deleted)


def list_notes(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
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
    return note_repo.list_notes(
        user_id,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )


def get_notes_by_ids(user_id: int, note_ids: List[str], include_deleted: bool = False) -> List[Note]:
    return note_repo.get_notes_by_ids(user_id, note_ids, include_deleted=include_deleted)
