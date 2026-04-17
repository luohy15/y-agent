"""Reminder service."""

import os
from datetime import datetime, timezone
from typing import List, Optional
from storage.dto.reminder import Reminder
from storage.repository import reminder as reminder_repo
from storage.util import generate_id, get_utc_iso8601_timestamp


def _get_configured_tz():
    """Return the configured timezone, falling back to system local."""
    from dateutil import tz as dateutil_tz
    tz_name = os.getenv("Y_AGENT_TIMEZONE")
    if tz_name:
        tz = dateutil_tz.gettz(tz_name)
        if tz:
            return tz
    return dateutil_tz.tzlocal()


def _local_to_utc(local_str: str) -> str:
    """Convert a local datetime string to UTC ISO 8601."""
    local_tz = _get_configured_tz()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(local_str, fmt)
            dt = dt.replace(tzinfo=local_tz)
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_dt.microsecond // 1000:03d}Z"
        except ValueError:
            continue
    if local_str.endswith("Z"):
        return local_str
    raise ValueError(f"Cannot parse datetime: {local_str}")


def add_reminder(
    user_id: int,
    title: str,
    remind_at: str,
    description: Optional[str] = None,
    todo_id: Optional[str] = None,
    calendar_event_id: Optional[str] = None,
) -> Reminder:
    utc_remind_at = _local_to_utc(remind_at)
    reminder = Reminder(
        reminder_id=generate_id(),
        title=title,
        remind_at=utc_remind_at,
        description=description,
        todo_id=todo_id,
        calendar_event_id=calendar_event_id,
    )
    return reminder_repo.save_reminder(user_id, reminder)


def update_reminder(user_id: int, reminder_id: str, **fields) -> Optional[Reminder]:
    reminder = reminder_repo.get_reminder(user_id, reminder_id)
    if not reminder:
        return None
    for key, value in fields.items():
        if key == "remind_at" and value is not None:
            value = _local_to_utc(value)
        if hasattr(reminder, key):
            setattr(reminder, key, value)
    return reminder_repo.save_reminder(user_id, reminder)


def cancel_reminder(user_id: int, reminder_id: str) -> Optional[Reminder]:
    reminder = reminder_repo.get_reminder(user_id, reminder_id)
    if not reminder:
        return None
    if reminder.status != "pending":
        return None
    reminder.status = "cancelled"
    return reminder_repo.save_reminder(user_id, reminder)


def get_reminder(user_id: int, reminder_id: str) -> Optional[Reminder]:
    return reminder_repo.get_reminder(user_id, reminder_id)


def list_reminders(
    user_id: int,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Reminder]:
    return reminder_repo.list_reminders(user_id, status=status, limit=limit)


def get_pending_reminders(before: Optional[str] = None) -> List[dict]:
    """Get all pending reminders due before the given time (or now)."""
    if before is None:
        before = get_utc_iso8601_timestamp()
    return reminder_repo.get_pending_reminders(before)


def mark_sent(user_id: int, reminder_id: str) -> Optional[Reminder]:
    return reminder_repo.mark_sent(user_id, reminder_id, get_utc_iso8601_timestamp())
