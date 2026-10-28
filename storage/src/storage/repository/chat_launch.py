"""Append-only launch history. There is no update."""

from typing import Optional

from storage.database.base import get_db
from storage.entity.chat_launch import ChatLaunchEntity
from storage.util import generate_id, get_unix_timestamp, get_utc_iso8601_timestamp


def insert_launch(
    user_id: int,
    chat_id: str,
    launched_at: str,
    capability: str,
    *,
    trace_id: Optional[str] = None,
    run_seq: Optional[int] = None,
    bot_name: Optional[str] = None,
    backend: Optional[str] = None,
    model: Optional[str] = None,
    requested_effort: Optional[str] = None,
    launch_effort: Optional[str] = None,
    input_message_ids: Optional[list] = None,
) -> ChatLaunchEntity:
    """Insert one spawn row and return it. Never updates an existing row."""
    if capability not in ("declared", "not_required"):
        raise ValueError(f"unsupported launch capability {capability!r}")
    with get_db() as session:
        row = ChatLaunchEntity(
            launch_id=generate_id(),
            user_id=user_id,
            chat_id=chat_id,
            trace_id=trace_id,
            run_seq=run_seq,
            launched_at=launched_at,
            bot_name=bot_name,
            backend=backend,
            model=model,
            requested_effort=requested_effort,
            launch_effort=launch_effort,
            capability=capability,
            input_message_ids=list(input_message_ids or []),
            created_at=get_utc_iso8601_timestamp(),
            updated_at=get_utc_iso8601_timestamp(),
            created_at_unix=get_unix_timestamp(),
            updated_at_unix=get_unix_timestamp(),
        )
        session.add(row)
        session.flush()
        session.expunge(row)
        return row
