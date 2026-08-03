"""Routine service.

A routine is a recurring scheduled task that auto-fires a chat dispatch on a
cron schedule. Schedules are evaluated in `Y_AGENT_TIMEZONE`; `last_run_at`
and `created_at` are stored as UTC ISO 8601.

Only PR 3 (`y routine run`) and PR 4 (admin Lambda `tick_routines`) call
`fire_routine`; PR 1 implements it end-to-end so those PRs can wire up cleanly.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

from storage.dto.routine import Routine
from storage.repository import routine as routine_repo
from storage.util import generate_id, generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp

VALID_ACTIONS = ("chat", "vm_command")

# Headroom for one command plus a cold EC2 wake inside the admin Lambda's 300s
# ceiling (A8); see pages/decision-3020-module-system-vm-command-timeout.md.
VM_COMMAND_TIMEOUT = 180

# last_run_status is a free-form column read by `y routine get`/`list`; keep a
# failure message readable instead of dumping a full traceback into it.
MAX_STATUS_LEN = 300


def _validate_routine_payload(action: str, message: Optional[str], command: Optional[List[str]]) -> None:
    """Validate the action/message/command combination before it is stored.

    'chat' requires a non-empty message; 'vm_command' requires a non-empty
    argv list of strings (never a shell string — see run_vm_command).
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action {action!r}; expected one of {VALID_ACTIONS}")
    if action == "chat":
        if not message:
            raise ValueError("message is required for action='chat'")
    else:
        if not command:
            raise ValueError("command is required for action='vm_command'")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            raise ValueError("command must be a list of argv strings for action='vm_command'")


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
    message: Optional[str] = None,
    description: Optional[str] = None,
    target_topic: Optional[str] = None,
    target_skill: Optional[str] = None,
    work_dir: Optional[str] = None,
    backend: Optional[str] = None,
    guard: Optional[str] = None,
    enabled: bool = True,
    action: str = "chat",
    command: Optional[List[str]] = None,
    vm_name: Optional[str] = None,
) -> Routine:
    _validate_routine_payload(action, message, command)
    routine = Routine(
        routine_id=generate_id(),
        name=name,
        schedule=schedule,
        message=message or "",
        description=description,
        target_topic=target_topic,
        target_skill=target_skill,
        work_dir=work_dir,
        backend=backend,
        guard=guard,
        enabled=enabled,
        action=action,
        command=command,
        vm_name=vm_name,
    )
    return routine_repo.save_routine(user_id, routine)


def update_routine(user_id: int, routine_id: str, **fields) -> Optional[Routine]:
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        return None
    if fields.get("guard") == "":
        fields["guard"] = None  # `--guard ''` is the way to detach a guard
    for key, value in fields.items():
        if hasattr(routine, key):
            setattr(routine, key, value)
    _validate_routine_payload(routine.action, routine.message, routine.command)
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
    deleted = routine_repo.delete_routine(user_id, routine_id)
    if deleted:
        from storage.service import tag as tag_service
        tag_service.delete_for_entity(user_id, "routine", routine_id)
    return deleted


def get_routine(user_id: int, routine_id: str) -> Optional[Routine]:
    return routine_repo.get_routine(user_id, routine_id)


def list_routines(
    user_id: int,
    enabled: Optional[bool] = None,
    limit: int = 50,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[Routine]:
    return routine_repo.list_routines(
        user_id, enabled=enabled, limit=limit, tag=tag,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )


def _resolve_routine_for_tag(user_id: int, entity_id: str):
    """Hydration resolver for y tag get (public id + name)."""
    routine = routine_repo.get_routine(user_id, entity_id)
    if not routine:
        return None
    return {"id": routine.routine_id, "title": routine.name or ""}


from storage.service.tag import register_resolver  # noqa: E402
register_resolver("routine", _resolve_routine_for_tag)


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


def stamp_routine(user_id: int, routine_id: str, status: str) -> Optional[Routine]:
    """Stamp last_run_at and last_run_status without creating a chat."""
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        return None
    routine.last_run_at = get_utc_iso8601_timestamp()
    routine.last_run_status = status
    return routine_repo.save_routine(user_id, routine)


def evaluate_guard(user_id: int, guard: str) -> bool:
    """Import and call a routine guard function.

    `guard` is a dotted path in `module:function` form.  The function is
    called with `(user_id)` and must return a truthy value for the routine
    to fire.
    """
    import importlib

    module_path, _, func_name = guard.partition(":")
    if not func_name:
        raise ValueError(f"Invalid guard format (expected 'module:func'): {guard}")
    mod = importlib.import_module(module_path)
    func = getattr(mod, func_name)
    return bool(func(user_id))


def _run_coro_sync(coro):
    """Run `coro` to completion from sync code.

    fire_routine is called both from the admin Lambda's plain-sync tick loop
    (no event loop running) and from the FastAPI `/routine/run` endpoint
    (an `async def` handler with a loop already running on this thread), and
    `asyncio.run()` raises if a loop is already running. When one is, run the
    coroutine to completion on its own loop in a throwaway thread instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _run_vm_command_for_routine(user_id: int, vm_name: Optional[str], command: List[str], timeout: float) -> str:
    from agent.module_host import request_owner, run_vm_command

    with request_owner(user_id):
        return await run_vm_command(user_id, vm_name, command, timeout=timeout)


def _fire_vm_command_routine(user_id: int, routine: Routine) -> str:
    """Run routine.command on the routine owner's VM via the host contract.

    Creates no chat row (last_chat_id is left untouched). A non-zero exit or
    timeout is a normal outcome for a command run here — it is stamped into
    last_run_status rather than raised past the caller, unlike a 'chat'
    dispatch failure.
    """
    try:
        _run_coro_sync(
            _run_vm_command_for_routine(user_id, routine.vm_name, routine.command, VM_COMMAND_TIMEOUT)
        )
        status = "ok"
    except Exception as e:
        first_line = str(e).splitlines()[0] if str(e) else e.__class__.__name__
        status = f"error: {first_line}"[:MAX_STATUS_LEN]
        logger.warning(
            "[fire_routine] vm_command routine={} failed: {}", routine.routine_id, e
        )

    routine.last_run_at = get_utc_iso8601_timestamp()
    routine.last_run_status = status
    routine_repo.save_routine(user_id, routine)
    return ""


def fire_routine(user_id: int, routine_id: str) -> str:
    """Fire a routine: dispatch its action, stamp routine state.

    For action='chat' (default), builds a chat, dispatches to the worker, and
    returns the new chat_id; raises on schedule / dispatch errors so the admin
    Lambda's `tick_routines` can capture the message in `last_run_status` and
    notify Telegram. For action='vm_command', runs the stored argv on the
    owner's VM, creates no chat row, and returns "" (see _fire_vm_command_routine).
    """
    routine = routine_repo.get_routine(user_id, routine_id)
    if not routine:
        raise ValueError(f"Routine {routine_id} not found")

    if routine.action == "vm_command":
        return _fire_vm_command_routine(user_id, routine)

    from storage.dto.chat import Chat, Message
    from storage.repository.chat import _save_chat_sync
    from storage.service import chat as chat_service

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
