"""Scheduled trace liveness watchdog (todo 3458 phase 4, todo 3506 S2, todo 4070,
todo 4077).

Observation plus one conditional transition. An `active` trace with no live
machine evidence becomes `awaiting` once, with a bounded fault detail folded
into the shared owner-notice history entry. A trace that already has chats
needs no extra idle duration; a zero-chat trace still waits out the 24-hour
backstop. The pass only claims `active` todos (the query already excludes
anything already in the awaiting inbox); it never touches progress or chats,
and never enqueues work. Periodic orphan-running-chat maintenance is a
separate step run by the scheduled dispatcher before this one.

Since todo 4070, runtime evidence is probed once per owner by
`refresh_trace_runtime` and stored in `trace_runtime_snapshot`; this pass and
its under-lock recheck only read chat state and that store. They never probe
tmux, and only a snapshot from this same pass can prove `ended`.

Since todo 4077 the under-lock idle claim builder is shared with the
session-end reconcile (`worker.session_end`), so a normal turn closeout uses
exactly the watchdog's suppressors and never diverges from them. This pass
stays the fallback for abnormal endings.
"""

from typing import Optional

from loguru import logger

from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.todo import TodoEntity
from storage.repository import chat_wakeup as wakeup_repo
from storage.repository import dev_release as dev_release_repo
from storage.repository.trace_runtime import get_snapshots, trace_runtime_roles
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import todo as todo_service
from storage.service.trace_runtime import derive_runtime
from storage.util import get_unix_timestamp
from worker.process_manager import get_process, get_running_processes
from worker.steps.trace_runtime import refresh_trace_runtime

LOCK_NAME = "check_trace_liveness"
ZERO_CHAT_BACKSTOP_SECONDS = 24 * 60 * 60
BATCH_SIZE = 200
ERROR_TEXT_LIMIT = 1000
SUPPRESSING_STATES = {"session", "child", "tmux"}


def classify(*, live, chat_count, created_at_ms, now_ms) -> Optional[str]:
    """Pure classifier: the stall reason (idle / backstop) or None.

    A live process/chat suppresses. Zero-chat todos only ever fall under the
    24-hour backstop. A trace that already has chats is idle as soon as that
    evidence is gone; there is no extra idle duration.
    """
    if live:
        return None
    if chat_count == 0:
        if not created_at_ms:
            return None
        return "backstop" if now_ms - created_at_ms >= ZERO_CHAT_BACKSTOP_SECONDS * 1000 else None
    return "idle"


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


def _fault_detail(reason, chat_id, outcome, error_text) -> str:
    detail = {
        "idle": "No running session.",
        "backstop": f"Active for over {ZERO_CHAT_BACKSTOP_SECONDS // 3600} hours with no chat on the trace.",
        "session_end": "Session ended; nothing else is running on the trace.",
    }[reason]
    if chat_id:
        detail += f" Last chat {chat_id}: exit {outcome}."
        excerpt = todo_service.notice_excerpt(error_text)
        if excerpt:
            detail += f" {excerpt[:ERROR_TEXT_LIMIT]}"
    return detail


def _assistant_text_from_entity(row) -> Optional[str]:
    from storage.repository.chat import _entity_to_chat

    chat = _entity_to_chat(row) if row else None
    last = next((m for m in reversed(chat.messages) if m.role == "assistant"), None) if chat else None
    return last.content if last and isinstance(last.content, str) else None


def _derive_for(session, user_id: int, todo_id: str, now_ms: int, pass_started_ms: int) -> dict:
    roles = trace_runtime_roles(session, {user_id}, {todo_id}).get((user_id, todo_id))
    snapshot = get_snapshots(session, {user_id}).get(user_id)
    return derive_runtime(roles, snapshot, todo_id, now_ms, observed_after_ms=pass_started_ms)


def claim_idle_trace(user_id: int, todo, reason: str, observed_after_ms: int) -> dict:
    """One conditional claim under the todo lock, shared by both claim callers.

    `todo` only needs `todo_id` and `updated_at_unix`; the owner is explicit so
    a todo DTO without `user_id` works. The recheck re-validates every
    suppressor against the locked row, exactly like the watchdog pass. Returns
    `{"outcome": claimed|suppressed|failed, "evidence": <named suppressor or
    None>, "runtime_state": <derived state or None>, "rechecked": <recheck
    ran>, "chat_id": <newest chat or None>}` so a caller can persist why it did
    not claim. The owner notice is sent by the shared post-commit hook on
    entry.
    """
    todo_id = todo.todo_id
    seen = {"evidence": None, "runtime_state": None, "rechecked": False, "chat_id": None}

    def recheck(session, row):
        # Re-read the roles and the snapshot inside the locked transaction:
        # no network I/O crosses the todo lock.
        seen["rechecked"] = True
        now_ms = get_unix_timestamp()
        runtime = _derive_for(session, user_id, todo_id, now_ms, observed_after_ms)
        state = runtime["state"]
        seen["runtime_state"] = state
        if state in SUPPRESSING_STATES:
            seen["evidence"] = state
            return None
        if state != "ended":
            return None
        if dev_release_repo.has_pending_waiter(session, user_id, todo_id):
            seen["evidence"] = "waiter"
            return None
        if wakeup_repo.has_pending_wakeup(session, user_id, todo_id, now_ms):
            seen["evidence"] = "wakeup"
            return None
        chats = (session.query(ChatEntity.chat_id, ChatEntity.status, ChatEntity.updated_at_unix)
                 .filter_by(user_id=user_id, trace_id=todo_id)
                 .order_by(ChatEntity.updated_at_unix.desc()).all())
        if any(c.status == "running" for c in chats):
            seen["evidence"] = "session"
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
                seen["evidence"] = "process"
                return None
            if c is chats[0]:
                newest_record = record
        current = classify(
            live=False, chat_count=len(chats),
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
        seen["chat_id"] = chat_id
        # The caller's reason labels the detail; `current` only re-validates
        # that a fault still applies under the lock.
        return _fault_detail(reason, chat_id, outcome, error_text), chat_id

    try:
        _todo, changed = todo_service.claim_fault(
            user_id, todo_id, expected_updated_at_unix=todo.updated_at_unix, recheck=recheck,
        )
    except Exception:
        logger.exception("check_trace_liveness: evidence recheck failed, no claim: user_id={} todo_id={}", user_id, todo_id)
        return {**seen, "outcome": "failed"}
    return {**seen, "outcome": "claimed" if changed else "suppressed"}


def _claim_fault(todo, reason, pass_started_ms: int) -> str:
    """Watchdog pass wrapper: only the claim outcome matters here."""
    return claim_idle_trace(todo.user_id, todo, reason, pass_started_ms)["outcome"]


async def run_pass(now_ms: Optional[int] = None, pass_started_ms: Optional[int] = None) -> dict:
    """One watchdog pass over every owner's active todos.

    `pass_started_ms` is the refresh's observation timestamp: only a snapshot
    written by this pass (at or after it) can prove `ended`.
    """
    now_ms = now_ms or get_unix_timestamp()
    pass_started_ms = pass_started_ms if pass_started_ms is not None else now_ms
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

    counts = dict(scanned=0, candidates=0, claimed=0, suppressed=0, failed=0, runtime_unknown=0)
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
            user_ids = {t.user_id for t in todos}
            trace_ids = {t.todo_id for t in todos}
            roles = trace_runtime_roles(session, user_ids, trace_ids)
            snapshots = get_snapshots(session, user_ids)
            wakeup_traces = wakeup_repo.pending_wakeup_traces(session, user_ids, trace_ids, now_ms)
        counts["scanned"] += len(todos)
        for todo in todos:
            key = (todo.user_id, todo.todo_id)
            runtime = derive_runtime(
                roles.get(key), snapshots.get(todo.user_id), todo.todo_id, now_ms,
                observed_after_ms=pass_started_ms,
            )
            if runtime["state"] in SUPPRESSING_STATES:
                counts["suppressed"] += 1
                continue
            if runtime["state"] == "unknown":
                counts["runtime_unknown"] += 1
                continue
            if key in live_traces or key in wakeup_traces:
                continue
            chat_count = (roles.get(key) or (0, 0, 0, 0))[0]
            reason = classify(
                live=False, chat_count=chat_count,
                created_at_ms=todo.created_at_unix, now_ms=now_ms,
            )
            if reason is None:
                continue
            counts["candidates"] += 1
            outcome = _claim_fault(todo, reason, pass_started_ms)
            counts[outcome] += 1
    return {"status": "ok", "action": LOCK_NAME, **counts}


async def handle_check_trace_liveness() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("check_trace_liveness: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}
    try:
        # One probe per owner, then the read-only decision, in the same lock.
        pass_started_ms = get_unix_timestamp()
        refresh = await refresh_trace_runtime(pass_started_ms)
        result = await run_pass(now_ms=pass_started_ms, pass_started_ms=pass_started_ms)
        if result["status"] == "ok":
            pipeline_lock_service.record_success(LOCK_NAME)
        logger.info("check_trace_liveness: refresh={} result={}", refresh, result)
        return {**result, "refresh": refresh}
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
