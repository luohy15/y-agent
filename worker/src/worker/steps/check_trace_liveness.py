"""Scheduled trace liveness watchdog (todo 3458 phase 4, todo 3506 S2).

Observation plus one conditional transition. A trace that is not live and
silent past its grace becomes `awaiting` once, with a bounded fault detail
folded into the shared owner-notice history entry. The pass only claims
`active` todos (the query already excludes anything already in the awaiting
inbox); it never touches progress or chats, and never enqueues work. Periodic
orphan-running-chat maintenance is a separate step run by the scheduled
dispatcher before this one.
"""

from typing import Optional

from loguru import logger
from sqlalchemy import case, func

from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.todo import TodoEntity
from storage.repository import dev_release as dev_release_repo
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import todo as todo_service
from storage.util import get_unix_timestamp
from worker.process_manager import get_process, get_running_processes

LOCK_NAME = "check_trace_liveness"
IDLE_GRACE_SECONDS = 10 * 60
ZERO_CHAT_BACKSTOP_SECONDS = 24 * 60 * 60
BATCH_SIZE = 200
ERROR_TEXT_LIMIT = 1000


def _last_activity(todo_updated_ms, chat_max_ms) -> Optional[int]:
    values = [v for v in (todo_updated_ms, chat_max_ms) if v]
    return max(values) if values else None


def classify(*, live, chat_count, last_activity_ms, created_at_ms, now_ms) -> Optional[str]:
    """Pure classifier: the stall reason (idle / backstop) or None.

    A live process/chat suppresses; zero-chat todos only ever fall under the
    24-hour backstop; everything else uses the 10-minute idle grace against
    the newer of the todo's own timestamp and its newest chat's activity.
    """
    if live:
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


def _fault_detail(reason, chat_id, outcome, error_text) -> str:
    detail = {
        "idle": f"No running session and no activity for {IDLE_GRACE_SECONDS // 60}+ minutes.",
        "backstop": f"Active for over {ZERO_CHAT_BACKSTOP_SECONDS // 3600} hours with no chat on the trace.",
    }[reason]
    if chat_id:
        detail += f" Last chat {chat_id}: exit {outcome}."
        if error_text:
            detail += f" {error_text[:ERROR_TEXT_LIMIT]}"
    return detail


def _assistant_text_from_entity(row) -> Optional[str]:
    from storage.repository.chat import _entity_to_chat

    chat = _entity_to_chat(row) if row else None
    last = next((m for m in reversed(chat.messages) if m.role == "assistant"), None) if chat else None
    return last.content if last and isinstance(last.content, str) else None


def _claim_fault(todo, reason) -> str:
    """One conditional claim under the todo lock; the shared notice hook sends on entry."""
    user_id, todo_id = todo.user_id, todo.todo_id

    def recheck(session, row):
        if dev_release_repo.has_pending_waiter(session, user_id, todo_id):
            return None
        chats = (session.query(ChatEntity.chat_id, ChatEntity.status, ChatEntity.updated_at_unix)
                 .filter_by(user_id=user_id, trace_id=todo_id)
                 .order_by(ChatEntity.updated_at_unix.desc()).all())
        if any(c.status == "running" for c in chats):
            return None
        # Identity, outcome and error text in the notice all come from the
        # newest chat. An older chat's record is only live/not-live evidence;
        # its outcome is never attributed to the newest chat.
        newest_record = None
        for c in chats:
            record = get_process(c.chat_id)
            if record.get("user_id") != user_id:
                continue
            if record.get("status") == "running":
                return None
            if c is chats[0]:
                newest_record = record
        current = classify(
            live=False, chat_count=len(chats),
            last_activity_ms=_last_activity(row.updated_at_unix, chats[0].updated_at_unix if chats else None),
            created_at_ms=row.created_at_unix, now_ms=get_unix_timestamp(),
        )
        if current is None:
            return None
        chat_id = chats[0].chat_id if chats else None
        outcome = (newest_record or {}).get("status") or "unknown"
        error_text = None
        if chat_id and outcome in {"error", "timeout"}:
            newest_row = session.query(ChatEntity).filter_by(
                user_id=user_id, chat_id=chat_id).first()
            error_text = _assistant_text_from_entity(newest_row)
        return _fault_detail(current, chat_id, outcome, error_text), chat_id

    try:
        _todo, changed = todo_service.claim_fault(
            user_id, todo_id, expected_updated_at_unix=todo.updated_at_unix, recheck=recheck,
        )
    except Exception:
        logger.exception("check_trace_liveness: evidence recheck failed, no claim: user_id={} todo_id={}", user_id, todo_id)
        return "failed"
    return "claimed" if changed else "suppressed"


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

    counts = dict(scanned=0, candidates=0, claimed=0, suppressed=0, failed=0)
    last_id = 0
    while True:
        with get_db() as session:
            todos = (session.query(TodoEntity.id, TodoEntity.user_id, TodoEntity.todo_id, TodoEntity.name,
                                   TodoEntity.status,
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
                live=key in live_traces or running > 0, chat_count=chat_count,
                last_activity_ms=_last_activity(todo.updated_at_unix, chat_max),
                created_at_ms=todo.created_at_unix, now_ms=now_ms,
            )
            if reason is None:
                continue
            counts["candidates"] += 1
            outcome = _claim_fault(todo, reason)
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
