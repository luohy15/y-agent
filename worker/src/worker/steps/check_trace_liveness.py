"""Scheduled trace liveness watchdog (todo 3458 phase 4).

Observation plus one conditional transition. A trace that is not live, not in
the inbox, and silent past its grace becomes ``awaiting=stalled`` once, with one
push to the owner's default Telegram target. The pass writes only ``awaiting``
(and history) through the shared conditional claim; it never touches status,
progress, or chats, and never enqueues work. Periodic orphan-running-chat
maintenance is a separate step run by the scheduled dispatcher before this one.
"""

from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import case, func

from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.todo import TodoEntity
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import todo as todo_service
from storage.util import get_unix_timestamp
from worker.process_manager import get_process, get_running_processes

LOCK_NAME = "check_trace_liveness"
IDLE_GRACE_SECONDS = 10 * 60
EXTERNAL_GRACE_SECONDS = 60 * 60
ZERO_CHAT_BACKSTOP_SECONDS = 24 * 60 * 60
BATCH_SIZE = 200
VISIBLE_INBOX = {"question", "review", "stalled"}
ERROR_TEXT_LIMIT = 1000


def _until_ms(awaiting_until: Optional[str]) -> Optional[int]:
    if not awaiting_until:
        return None
    try:
        return int(datetime.fromisoformat(awaiting_until.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _last_activity(todo_updated_ms, chat_max_ms) -> Optional[int]:
    values = [v for v in (todo_updated_ms, chat_max_ms) if v]
    return max(values) if values else None


def classify(*, status, awaiting, awaiting_until, live, chat_count, last_activity_ms,
             created_at_ms, now_ms) -> Optional[str]:
    """Pure classifier: the stall reason (idle / external / backstop) or None.

    Each suppressor stands alone: a non-active todo, a visible inbox reason, a
    live process or running chat, or an unexpired grace each prevents a claim.
    Zero-chat todos only ever fall under the 24-hour backstop.
    """
    if status != "active" or awaiting in VISIBLE_INBOX or live:
        return None
    if awaiting == "external":
        deadline = _until_ms(awaiting_until)
        if deadline is None:
            if last_activity_ms is None:
                return None
            deadline = last_activity_ms + EXTERNAL_GRACE_SECONDS * 1000
        return "external" if now_ms >= deadline else None
    if awaiting is not None:
        return None
    if chat_count == 0:
        if not created_at_ms:
            return None
        return "backstop" if now_ms - created_at_ms >= ZERO_CHAT_BACKSTOP_SECONDS * 1000 else None
    if last_activity_ms is None:
        return None
    return "idle" if now_ms - last_activity_ms >= IDLE_GRACE_SECONDS * 1000 else None


def _process_snapshot():
    """Fully paginated running-process snapshot, keyed by owner. Raises when unavailable."""
    live_traces, live_chats = set(), set()
    for record in get_running_processes():
        user_id = record.get("user_id")
        if user_id is None:
            continue
        if record.get("trace_id"):
            live_traces.add((user_id, record["trace_id"]))
        if record.get("chat_id"):
            live_chats.add((user_id, record["chat_id"]))
    return live_traces, live_chats


def _chat_aggregates(session, user_ids, trace_ids) -> dict:
    rows = (session.query(ChatEntity.user_id, ChatEntity.trace_id, func.count(ChatEntity.id),
                          func.max(ChatEntity.updated_at_unix),
                          func.sum(case((ChatEntity.status == "running", 1), else_=0)))
            .filter(ChatEntity.user_id.in_(user_ids), ChatEntity.trace_id.in_(trace_ids))
            .group_by(ChatEntity.user_id, ChatEntity.trace_id).all())
    return {(r[0], r[1]): (r[2], r[3], int(r[4] or 0)) for r in rows}


def _notice(todo, reason, chat_id, outcome, error_text) -> str:
    detail = {
        "idle": f"no running session and no activity for {IDLE_GRACE_SECONDS // 60}+ minutes.",
        "external": "the declared external wait expired with no running session.",
        "backstop": f"active for over {ZERO_CHAT_BACKSTOP_SECONDS // 3600} hours with no chat on the trace.",
    }[reason]
    text = f"Trace {todo.todo_id} ({todo.name}) is stalled: {detail}"
    if chat_id:
        text += f" Last chat {chat_id}: exit {outcome}."
        if error_text:
            text += f" {error_text[:ERROR_TEXT_LIMIT]}"
    return text


def _last_assistant_text(user_id, chat_id) -> Optional[str]:
    from storage.repository.chat import _entity_to_chat

    with get_db() as session:
        row = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).first()
        chat = _entity_to_chat(row) if row else None
    last = next((m for m in reversed(chat.messages) if m.role == "assistant"), None) if chat else None
    return last.content if last and isinstance(last.content, str) else None


def _claim_and_push(todo, reason) -> str:
    """One conditional claim under the todo lock; only the winner pushes."""
    from storage.service.telegram import resolve_target
    from storage.util import send_telegram_message_checked

    user_id, todo_id = todo.user_id, todo.todo_id
    evidence = {}

    def recheck(session, row):
        chats = (session.query(ChatEntity.chat_id, ChatEntity.status, ChatEntity.updated_at_unix)
                 .filter_by(user_id=user_id, trace_id=todo_id)
                 .order_by(ChatEntity.updated_at_unix.desc()).all())
        if any(c.status == "running" for c in chats):
            return False
        # Identity, outcome and error text in the notice all come from the
        # newest chat. An older chat's record is only live/not-live evidence;
        # its outcome is never attributed to the newest chat.
        newest_record = None
        for c in chats:
            record = get_process(c.chat_id)
            if record.get("user_id") != user_id:
                continue
            if record.get("status") == "running":
                return False
            if c is chats[0]:
                newest_record = record
        current = classify(
            status=row.status, awaiting=row.awaiting, awaiting_until=row.awaiting_until, live=False,
            chat_count=len(chats),
            last_activity_ms=_last_activity(row.updated_at_unix, chats[0].updated_at_unix if chats else None),
            created_at_ms=row.created_at_unix, now_ms=get_unix_timestamp(),
        )
        if current is None:
            return False
        evidence["reason"] = current
        evidence["chat_id"] = chats[0].chat_id if chats else None
        evidence["outcome"] = (newest_record or {}).get("status") or "unknown"
        return True

    try:
        won = todo_service.claim_stalled(
            user_id, todo_id, expected_updated_at_unix=todo.updated_at_unix,
            expected_awaiting=todo.awaiting, recheck=recheck,
        )
    except Exception:
        logger.exception("check_trace_liveness: evidence recheck failed, no claim: user_id={} todo_id={}", user_id, todo_id)
        return "failed"
    if not won:
        return "suppressed"
    latest = todo_service.get_todo(user_id, todo_id)
    if not latest or latest.awaiting != "stalled":
        return "claimed"
    error_text = None
    if evidence.get("chat_id") and evidence["outcome"] in {"error", "timeout"}:
        error_text = _last_assistant_text(user_id, evidence["chat_id"])
    text = _notice(todo, evidence.get("reason", reason), evidence.get("chat_id"), evidence.get("outcome", "unknown"), error_text)
    try:
        target = resolve_target(user_id)
        if target and send_telegram_message_checked(target[0], target[1], text, target[2]):
            return "pushed"
    except Exception:
        logger.exception("check_trace_liveness: push failed, inbox retained: user_id={} todo_id={}", user_id, todo_id)
    return "claimed"


def run_pass(now_ms: Optional[int] = None) -> dict:
    """One watchdog pass over every owner's active todos."""
    now_ms = now_ms or get_unix_timestamp()
    try:
        live_traces, live_chats = _process_snapshot()
    except Exception:
        logger.exception("check_trace_liveness: process snapshot unavailable, aborting without writes")
        return {"status": "error", "action": LOCK_NAME, "reason": "process snapshot unavailable"}
    if live_chats:
        with get_db() as session:
            rows = (session.query(ChatEntity.user_id, ChatEntity.chat_id, ChatEntity.trace_id)
                    .filter(ChatEntity.chat_id.in_({chat_id for _, chat_id in live_chats}))
                    .filter(ChatEntity.trace_id.isnot(None)).all())
        live_traces |= {(r.user_id, r.trace_id) for r in rows if (r.user_id, r.chat_id) in live_chats}

    counts = dict(scanned=0, candidates=0, claimed=0, pushed=0, suppressed=0, failed=0)
    last_id = 0
    while True:
        with get_db() as session:
            todos = (session.query(TodoEntity.id, TodoEntity.user_id, TodoEntity.todo_id, TodoEntity.name,
                                   TodoEntity.status, TodoEntity.awaiting, TodoEntity.awaiting_until,
                                   TodoEntity.updated_at_unix, TodoEntity.created_at_unix)
                     .filter(TodoEntity.status == "active", TodoEntity.id > last_id)
                     .order_by(TodoEntity.id.asc()).limit(BATCH_SIZE).all())
            if not todos:
                break
            last_id = todos[-1].id
            aggregates = _chat_aggregates(session, {t.user_id for t in todos}, {t.todo_id for t in todos})
        counts["scanned"] += len(todos)
        for todo in todos:
            key = (todo.user_id, todo.todo_id)
            chat_count, chat_max, running = aggregates.get(key, (0, None, 0))
            reason = classify(
                status=todo.status, awaiting=todo.awaiting, awaiting_until=todo.awaiting_until,
                live=key in live_traces or running > 0, chat_count=chat_count,
                last_activity_ms=_last_activity(todo.updated_at_unix, chat_max),
                created_at_ms=todo.created_at_unix, now_ms=now_ms,
            )
            if reason is None:
                continue
            counts["candidates"] += 1
            outcome = _claim_and_push(todo, reason)
            if outcome == "pushed":
                counts["claimed"] += 1
            counts[outcome] += 1
    return {"status": "ok", "action": LOCK_NAME, **counts}


async def handle_check_trace_liveness() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("check_trace_liveness: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}
    try:
        result = run_pass()
        if result["status"] == "ok":
            pipeline_lock_service.record_success(LOCK_NAME)
        logger.info("check_trace_liveness: {}", result)
        return result
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
