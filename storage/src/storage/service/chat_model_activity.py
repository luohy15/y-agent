"""Derived y-agent chat sessions and answered turns by assistant model."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from loguru import logger

from storage.repository import chat_model_activity as repo
from storage.service import user_preference as user_pref_service
from storage.util import _time_filter_tz, get_unix_timestamp, local_today


CHAT_MODEL_ALIASES = {
    "grok-4.6": "grok-4.6-build",
}
WATERMARK_KEY = "chat_model_activity_watermark"
COVERAGE_KEY = "chat_model_activity_coverage"
SYNC_OVERLAP_MS = 5 * 60 * 1000


def usage_model_id(chat_model: str) -> str:
    return CHAT_MODEL_ALIASES.get(chat_model, chat_model)


def _message_date(message: dict, tz_name: str | None = None) -> date | None:
    unix_timestamp = message.get("unix_timestamp")
    if unix_timestamp is not None:
        try:
            return datetime.fromtimestamp(int(unix_timestamp) / 1000, _time_filter_tz(tz_name)).date()
        except (TypeError, ValueError, OSError):
            pass
    timestamp = message.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_time_filter_tz(tz_name)).date()


def attribute_messages(messages: list[dict], tz_name: str | None = None) -> list[dict]:
    """Fold one transcript into `(usage_date, model, turns)` fact rows.

    Every attributed assistant message establishes a session fact on its local
    output date. A maximal run of consecutive user messages opens one pending
    prompt group; the first later attributed assistant message counts that group
    as one turn. Tool and unattributed assistant messages neither open nor close
    the group.
    """
    facts: dict[tuple[date, str], int] = defaultdict(int)
    pending_prompt = False
    in_user_run = False

    for message in messages:
        role = message.get("role")
        if role == "user":
            if not in_user_run:
                pending_prompt = True
                in_user_run = True
            continue

        if role != "assistant":
            continue

        model = message.get("model")
        attributed = isinstance(model, str) and bool(model.strip()) and model != "<synthetic>"
        if not attributed:
            continue
        usage_date = _message_date(message, tz_name)
        if usage_date is None:
            continue

        key = (usage_date, usage_model_id(model.strip()))
        facts.setdefault(key, 0)
        if pending_prompt:
            facts[key] += 1
            pending_prompt = False
        in_user_run = False

    return [
        {"usage_date": usage_date, "model": model, "turns": turns}
        for (usage_date, model), turns in sorted(facts.items())
    ]


def _messages(json_content: str) -> list[dict]:
    try:
        payload = json.loads(json_content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid chat json_content") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ValueError("chat json_content has no messages list")
    return payload["messages"]


def recompute_for_chat(
    user_id: int,
    chat_id: str,
    json_content: str,
    *,
    tz_name: str | None = None,
) -> int:
    rows = attribute_messages(_messages(json_content), tz_name)
    return repo.recompute_for_chat(user_id, chat_id, rows)


def _watermark(user_id: int) -> int:
    preference = user_pref_service.get_preference(user_id, WATERMARK_KEY)
    value = preference.value if preference else None
    return int(value.get("updated_at_unix") or 0) if isinstance(value, dict) else 0


def sync(user_id: int, since_unix: int | None = None) -> dict:
    """Incrementally recompute changed chats, then sweep deleted-chat facts.

    A new installation starts from the current revision rather than treating an
    incidental oldest chat as complete history. Historical coverage is created
    only by the explicit backfill command.
    """
    through_unix = get_unix_timestamp()
    stored_watermark = _watermark(user_id)
    initialized = stored_watermark > 0 or since_unix is not None
    if since_unix is not None:
        scan_from = max(0, since_unix)
    elif stored_watermark:
        scan_from = max(0, stored_watermark - SYNC_OVERLAP_MS)
    else:
        scan_from = max(0, through_unix - SYNC_OVERLAP_MS)

    try:
        result = repo.recompute_updated_chats(
            user_id,
            scan_from,
            through_unix,
            lambda json_content: attribute_messages(_messages(json_content)),
        )
    except Exception as exc:
        logger.warning("chat_model_activity: incremental sync failed: {}", exc)
        raise

    return {
        "status": "ok",
        **result,
        "initialized": initialized,
        "through_unix": through_unix,
    }


def backfill(
    user_id: int,
    from_date: date,
    to_date: date,
    *,
    tz_name: str | None = None,
) -> dict:
    """Recompute every chat, retaining only facts in an inclusive date window."""
    if to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    chats = 0
    rows = 0
    after_id = 0
    while batch := repo.list_chat_batch(user_id, after_id):
        for row_id, chat_id, json_content in batch:
            activity = [
                row for row in attribute_messages(_messages(json_content), tz_name)
                if from_date <= row["usage_date"] <= to_date
            ]
            rows += repo.recompute_for_chat(
                user_id,
                chat_id,
                activity,
                from_date=from_date,
                to_date=to_date,
            )
            chats += 1
            after_id = row_id
    deleted = repo.sweep_orphans(user_id)
    coverage_preference = user_pref_service.get_preference(user_id, COVERAGE_KEY)
    coverage_value = coverage_preference.value if coverage_preference else None
    existing_from = coverage_value.get("from_date") if isinstance(coverage_value, dict) else None
    coverage_from = min(existing_from, from_date.isoformat()) if existing_from else from_date.isoformat()
    user_pref_service.upsert_preference(
        user_id,
        COVERAGE_KEY,
        {"from_date": coverage_from},
    )
    return {
        "status": "ok",
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "chats": chats,
        "rows": rows,
        "deleted": deleted,
    }


def backfill_days(user_id: int, days: int, *, tz_name: str | None = None) -> dict:
    if days < 1:
        raise ValueError("days must be at least 1")
    to_date = local_today(tz_name)
    return backfill(
        user_id,
        to_date - timedelta(days=days - 1),
        to_date,
        tz_name=tz_name,
    )


def aggregate(
    user_id: int,
    from_date: date | None,
    to_date: date | None,
) -> dict:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    result = repo.aggregate(user_id, from_date, to_date)
    coverage_preference = user_pref_service.get_preference(user_id, COVERAGE_KEY)
    coverage_value = coverage_preference.value if coverage_preference else None
    coverage_from = coverage_value.get("from_date") if isinstance(coverage_value, dict) else None
    return {**result, "coverage_from": coverage_from}
