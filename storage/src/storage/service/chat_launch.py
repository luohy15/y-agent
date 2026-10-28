"""Per-spawn launch history."""

from storage.entity.chat_launch import ChatLaunchEntity
from storage.repository import chat_launch as launch_repo
from storage.util import get_utc_iso8601_timestamp


def record_spawn(
    user_id: int,
    chat_id: str,
    *,
    trace_id: str = None,
    run_seq: int = None,
    bot_name: str = None,
    backend: str = None,
    model: str = None,
    requested_effort: str = None,
    launch_effort: str = None,
    input_message_ids: list = None,
    launched_at: str = None,
) -> ChatLaunchEntity:
    """Record one actual spawn. A missing flag is NULL, never a guessed level."""
    capability = "declared" if launch_effort else "not_required"
    return launch_repo.insert_launch(
        user_id, chat_id, launched_at or get_utc_iso8601_timestamp(), capability,
        trace_id=trace_id, run_seq=run_seq, bot_name=bot_name, backend=backend,
        model=model, requested_effort=requested_effort, launch_effort=launch_effort,
        input_message_ids=input_message_ids,
    )
