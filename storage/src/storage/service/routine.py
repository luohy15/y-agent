"""Routine service.

A routine is a recurring scheduled task that auto-fires a chat dispatch on a
cron schedule. Schedules are evaluated in `Y_AGENT_TIMEZONE`; `last_run_at`
and `created_at` are stored as UTC ISO 8601.

Only PR 3 (`y routine run`) and PR 4 (admin Lambda `tick_routines`) call
`fire_routine`; PR 1 implements it end-to-end so those PRs can wire up cleanly.
"""

import os
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

from storage.dto.routine import Routine
from storage.repository import routine as routine_repo
from storage.util import generate_id, generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp


def _get_configured_tz():
    from dateutil import tz as dateutil_tz
    tz_name = os.getenv("Y_AGENT_TIMEZONE")
    if tz_name:
        tz = dateutil_tz.gettz(tz_name)
        if tz:
            return tz
    return dateutil_tz.tzlocal()


def _parse_utc_iso(ts: str) -> datetime:
    """Parse a UTC ISO 8601 timestamp produced by get_utc_iso8601_timestamp."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _next_run_at(schedule: str, base_iso: str) -> datetime:
    """Return the next fire time (timezone-aware UTC) after `base_iso` for the cron schedule.

    `base_iso` is a UTC ISO 8601 string. The cron expression is interpreted in
    `Y_AGENT_TIMEZONE` so users write schedules in their local time.
    """
    from croniter import croniter
    base_utc = _parse_utc_iso(base_iso)
    base_local = base_utc.astimezone(_get_configured_tz())
    itr = croniter(schedule, base_local)
    next_local = itr.get_next(datetime)
    return next_local.astimezone(timezone.utc)


def add_routine(
    user_id: int,
    name: str,
    schedule: str,
    message: str,
    description: Optional[str] = None,
    target_topic: Optional[str] = None,
    target_skill: Optional[str] = None,
    work_dir: Optional[str] = None,
    backend: Optional[str] = None,
    enabled: bool = True,
) -> Routine:
    routine = Routine(
        routine_id=generate_id(),
        name=name,
        schedule=schedule,
        message=message,
        description=description,
        target_topic=target_topic,
        target_skill=target_skill,
        work_dir=work_dir,
        backend=backend,
        enabled=enabled,
    )
    return routine_repo.save_routine(user_id, routine)


def update_routine(user_id: int, routine_id: str, **fields) -> Optional[Routine]:
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        return None
    for key, value in fields.items():
        if hasattr(routine, key):
            setattr(routine, key, value)
    return routine_repo.save_routine(user_id, routine)


def enable_routine(user_id: int, routine_id: str) -> Optional[Routine]:
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        return None
    routine.enabled = True
    return routine_repo.save_routine(user_id, routine)


def disable_routine(user_id: int, routine_id: str) -> Optional[Routine]:
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        return None
    routine.enabled = False
    return routine_repo.save_routine(user_id, routine)


def delete_routine(user_id: int, routine_id: str) -> bool:
    return routine_repo.delete_routine(user_id, routine_id)


def get_routine(user_id: int, routine_id: str) -> Optional[Routine]:
    return routine_repo.get_routine(user_id, routine_id)


def list_routines(
    user_id: int,
    enabled: Optional[bool] = None,
    limit: int = 50,
) -> List[Routine]:
    return routine_repo.list_routines(user_id, enabled=enabled, limit=limit)


def list_due_routines(now: Optional[datetime] = None) -> List[dict]:
    """Return enabled routines whose next computed fire time has elapsed.

    Each item: {"user_id": int, "routine": Routine}. `next_run` is computed on
    the fly via croniter from `last_run_at` (or `created_at` for never-fired
    routines), so the schema does not need a `next_run_at` column.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    enabled = routine_repo.list_enabled_routines()
    due = []
    for item in enabled:
        routine = item["routine"]
        base = routine.last_run_at or routine.created_at or get_utc_iso8601_timestamp()
        try:
            next_run = _next_run_at(routine.schedule, base)
        except Exception as e:
            logger.exception("[list_due_routines] invalid schedule routine={} schedule={} err={}",
                             routine.routine_id, routine.schedule, e)
            continue
        if next_run <= now:
            due.append(item)
    return due


def fire_routine(user_id: int, routine_id: str) -> str:
    """Fire a routine: build a chat, dispatch to worker, stamp routine state.

    Returns the new chat_id. Raises on schedule / dispatch errors so the admin
    Lambda's `tick_routines` can capture the message in `last_run_status` and
    notify Telegram.
    """
    from storage.dto.chat import Chat, Message
    from storage.repository.chat import _save_chat_sync
    from storage.service import chat as chat_service

    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        raise ValueError(f"Routine {routine_id} not found")

    chat_id = generate_id()
    msg_content = f"[routine:{routine.name}]\n{routine.message}"
    timestamp = get_utc_iso8601_timestamp()
    user_msg = Message(
        role="user",
        content=msg_content,
        timestamp=timestamp,
        unix_timestamp=get_unix_timestamp(),
        id=generate_message_id(),
    )

    chat = Chat(
        id=chat_id,
        create_time=timestamp,
        update_time=timestamp,
        messages=[user_msg],
        topic=routine.target_topic,
        skill=routine.target_skill,
        backend=routine.backend,
        work_dir=routine.work_dir,
        routine_id=routine.routine_id,
        running=True,
    )
    _save_chat_sync(user_id, chat)

    try:
        chat_service.send_chat_message(
            chat_id,
            user_id=user_id,
            work_dir=routine.work_dir,
            topic=routine.target_topic,
            skill=routine.target_skill,
            backend=routine.backend,
        )
    except Exception:
        routine.last_run_at = get_utc_iso8601_timestamp()
        routine.last_run_status = "error: dispatch failed"
        routine.last_chat_id = chat_id
        routine_repo.save_routine(user_id, routine)
        raise

    routine.last_run_at = get_utc_iso8601_timestamp()
    routine.last_run_status = "ok"
    routine.last_chat_id = chat_id
    routine_repo.save_routine(user_id, routine)

    return chat_id
