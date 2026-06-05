"""Note share service (pure DB)."""

from typing import Optional, Tuple

from storage.repository import note_share as note_share_repo
from storage.util import generate_id


def ensure_share(user_id: int, note_id: str, password_hash: Optional[str] = None) -> Tuple[str, bool]:
    """Idempotently ensure a note_share row exists for (user_id, note_id).

    Returns (share_id, created). When a share already exists, only updates its
    password hash if a non-None hash is supplied (keeps an existing password
    untouched when None is passed). Pure DB: no S3/SSH work here.
    """
    existing = note_share_repo.get_by_note_id(user_id, note_id, include_revoked=True)
    if existing:
        if existing.revoked_at is not None:
            note_share_repo.set_revoked(existing.share_id, None)
        if password_hash is not None:
            note_share_repo.set_password_hash(existing.share_id, password_hash)
        return existing.share_id, False
    share_id = generate_id()
    note_share_repo.create(user_id, share_id, note_id, password_hash=password_hash)
    return share_id, True
