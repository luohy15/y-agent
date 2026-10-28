"""Per-spawn launch history and the trace view of it."""

from datetime import datetime, timezone

from storage.entity.chat_launch import ChatLaunchEntity
from storage.entity.chat_request_usage import ChatRequestUsageEntity
from storage.database.base import get_db
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


def _unix_ms(stamp: str) -> int:
    text = stamp.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _at(stamp: str):
    text = stamp.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def view_for_chats(user_id: int, chat_ids: list[str], limit: int = 20) -> dict[str, list[dict]]:
    """Newest `limit` launches per chat, with applied levels counted in-window.

    A request belongs to the launch whose ``launched_at`` is <= ``requested_at``
    and whose next launch (if any) is still after ``requested_at``. The public
    share payload does not call this.
    """
    if not chat_ids:
        return {}
    result = {}
    usage_by_chat = {}
    with get_db() as session:
        usage_rows = session.query(
            ChatRequestUsageEntity.chat_id,
            ChatRequestUsageEntity.requested_at,
            ChatRequestUsageEntity.applied_effort,
        ).filter(
            ChatRequestUsageEntity.user_id == user_id,
            ChatRequestUsageEntity.chat_id.in_(chat_ids),
            ChatRequestUsageEntity.applied_effort.isnot(None),
        ).all()
        for row in usage_rows:
            usage_by_chat.setdefault(row.chat_id, []).append(row)
    for chat_id in chat_ids:
        newest = launch_repo.list_newest(user_id, chat_id, limit=limit)
        ordered = list(reversed(newest))
        views = []
        requests = usage_by_chat.get(chat_id, [])
        for index, launch in enumerate(ordered):
            start = _at(launch.launched_at)
            end = _at(ordered[index + 1].launched_at) if index + 1 < len(ordered) else None
            applied = {}
            for request in requests:
                try:
                    when = _at(request.requested_at)
                except (TypeError, ValueError):
                    continue
                if when < start or (end is not None and when >= end):
                    continue
                level = request.applied_effort
                applied[level] = applied.get(level, 0) + 1
            views.append({
                "launched_at_unix": _unix_ms(launch.launched_at),
                "bot_name": launch.bot_name,
                "model": launch.model,
                "requested_effort": launch.requested_effort,
                "launch_effort": launch.launch_effort,
                "applied": applied,
                "provider": "unconfirmed",
            })
        result[chat_id] = views
    return result
