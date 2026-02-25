"""Calendar event service."""

import os
import glob as globmod
from datetime import datetime, timezone
from typing import List, Optional
from storage.entity.dto import CalendarEvent
from storage.repository import calendar_event as event_repo
from storage.repository import todo as todo_repo
from storage.util import generate_id, get_utc_iso8601_timestamp


def _resolve_todo_id(user_id: int, todo_id: Optional[str]) -> Optional[str]:
    """Validate todo_id exists and return it. Raises ValueError if not found."""
    if todo_id is None:
        return None
    todo = todo_repo.get_todo(user_id, todo_id)
    if not todo:
        raise ValueError(f"Todo '{todo_id}' not found")
    return todo_id


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
    """Convert a local datetime string to UTC ISO 8601.

    Accepts formats: 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DDTHH:MM', 'YYYY-MM-DD'.
    Uses Y_AGENT_TIMEZONE env var if set, otherwise system local timezone.
    """
    local_tz = _get_configured_tz()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(local_str, fmt)
            dt = dt.replace(tzinfo=local_tz)
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_dt.microsecond // 1000:03d}Z"
        except ValueError:
            continue
    # If already UTC ISO 8601 with Z suffix, return as-is
    if local_str.endswith("Z"):
        return local_str
    raise ValueError(f"Cannot parse datetime: {local_str}")


def _utc_to_local(utc_str: str) -> str:
    """Convert UTC ISO 8601 string to local datetime string.

    Uses Y_AGENT_TIMEZONE env var if set, otherwise system local timezone.
    """
    utc_str_clean = utc_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(utc_str_clean)
    local_dt = dt.astimezone(_get_configured_tz())
    return local_dt.strftime("%Y-%m-%d %H:%M")


def add_event(
    user_id: int,
    summary: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    todo_id: Optional[str] = None,
    all_day: bool = False,
    source: Optional[str] = None,
) -> CalendarEvent:
    utc_start = _local_to_utc(start_time)
    utc_end = _local_to_utc(end_time) if end_time else None
    resolved_todo_id = _resolve_todo_id(user_id, todo_id)
    event = CalendarEvent(
        event_id=generate_id(),
        summary=summary,
        start_time=utc_start,
        end_time=utc_end,
        description=description,
        todo_id=resolved_todo_id,
        all_day=all_day,
        source=source,
    )
    return event_repo.save_event(user_id, event)


def update_event(user_id: int, event_id: str, **fields) -> Optional[CalendarEvent]:
    event = event_repo.get_event(user_id, event_id)
    if not event:
        return None
    for key, value in fields.items():
        if key in ("start_time", "end_time") and value is not None:
            value = _local_to_utc(value)
        elif key == "todo_id":
            value = _resolve_todo_id(user_id, value)
        if hasattr(event, key):
            setattr(event, key, value)
    return event_repo.save_event(user_id, event)


def delete_event(user_id: int, event_id: str) -> Optional[CalendarEvent]:
    event = event_repo.get_event(user_id, event_id)
    if not event:
        return None
    event.deleted_at = get_utc_iso8601_timestamp()
    return event_repo.save_event(user_id, event)


def restore_event(user_id: int, event_id: str) -> Optional[CalendarEvent]:
    event = event_repo.get_event(user_id, event_id, include_deleted=True)
    if not event or not event.deleted_at:
        return None
    event.deleted_at = None
    return event_repo.save_event(user_id, event)


def get_event(user_id: int, event_id: str) -> Optional[CalendarEvent]:
    return event_repo.get_event(user_id, event_id)


def list_events(
    user_id: int,
    date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    todo_id: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 50,
) -> List[CalendarEvent]:
    from datetime import timedelta
    utc_start = None
    utc_end = None
    if date:
        # Convert local date to UTC range covering the full local day
        tz = _get_configured_tz()
        day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        utc_start = day_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        utc_end = day_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        utc_start = _local_to_utc(start) if start else None
        utc_end = _local_to_utc(end) if end else None
    return event_repo.list_events(
        user_id, date=None, start=utc_start, end=utc_end,
        source=source, todo_id=todo_id,
        include_deleted=include_deleted, limit=limit,
    )


def list_deleted_events(user_id: int, limit: int = 50) -> List[CalendarEvent]:
    return event_repo.list_deleted_events(user_id, limit=limit)


def import_ics(user_id: int, ics_dir: str) -> int:
    """Import ICS files from a directory. Returns count of imported events."""
    from icalendar import Calendar

    count = 0
    ics_files = globmod.glob(os.path.join(ics_dir, "*.ics"))
    for filepath in ics_files:
        with open(filepath, "rb") as f:
            cal = Calendar.from_ical(f.read())
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            uid = str(component.get("UID", ""))
            if not uid:
                continue
            summary = str(component.get("SUMMARY", ""))
            description = str(component.get("DESCRIPTION", "")) or None
            status = str(component.get("STATUS", "CONFIRMED"))
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")

            all_day = False
            if dtstart:
                dt_val = dtstart.dt
                if isinstance(dt_val, datetime):
                    start_str = dt_val.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                else:
                    # date object = all-day event
                    start_str = dt_val.strftime("%Y-%m-%dT00:00:00.000Z")
                    all_day = True
            else:
                continue

            end_str = None
            if dtend:
                dt_val = dtend.dt
                if isinstance(dt_val, datetime):
                    end_str = dt_val.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                else:
                    end_str = dt_val.strftime("%Y-%m-%dT00:00:00.000Z")

            source_name = os.path.splitext(os.path.basename(filepath))[0]

            event = CalendarEvent(
                event_id=uid,
                source_id=uid,
                summary=summary,
                description=description if description else None,
                start_time=start_str,
                end_time=end_str,
                all_day=all_day,
                status=status,
                source=source_name,
            )
            event_repo.save_event(user_id, event)
            count += 1
    return count
