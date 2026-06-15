"""Claude status incident dedup state service."""

from typing import Optional

from storage.repository import claude_status_state as repo


def get_state(user_id: int, incident_guid: str):
    return repo.get_state(user_id, incident_guid)


def upsert_state(user_id: int, incident_guid: str, title: str, status: str) -> dict:
    return repo.upsert_state(user_id, incident_guid, title, status)


def mark_notified(user_id: int, incident_guid: str) -> None:
    repo.mark_notified(user_id, incident_guid)


def mark_resolved_notified(user_id: int, incident_guid: str) -> None:
    repo.mark_resolved_notified(user_id, incident_guid)
