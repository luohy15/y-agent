"""Normal-session-end trace reconcile (todo 4077).

When a Claude Code turn closes out normally, the worker probes the owner's
default VM once, stores that snapshot like the scheduled refresher does, and
runs the same under-lock idle claim the trace-liveness watchdog uses. If
nothing else can advance the trace, the todo moves `active -> awaiting`
immediately instead of waiting for the next watchdog tick. The watchdog stays
the abnormal-recovery fallback; this path never completes a todo and never
writes progress.

Every failure is logged and swallowed so the turn's closeout never depends on
it.
"""

from loguru import logger

from storage.repository.trace_runtime import upsert_snapshot
from storage.service import todo as todo_service
from storage.util import get_unix_timestamp
from worker.steps.check_trace_liveness import claim_idle_trace
from worker.steps.trace_runtime import probe_owner

ROOT_TOPIC = "manager"
REASON = "session_end"


def should_reconcile(chat) -> bool:
    """Only a persisted, non-root trace belongs to a session-end reconcile.

    Root chats carry queue traces, not a trace this turn owns; a chat without a
    persisted trace has nothing to reconcile.
    """
    return bool((chat.trace_id or "").strip()) and chat.topic != ROOT_TOPIC


async def reconcile_session_end(user_id: int, chat) -> dict:
    """Reconcile one normally completed turn's trace. Never raises."""
    trace_id = (chat.trace_id or "").strip()
    if not should_reconcile(chat):
        return {"status": "skip", "reason": "root topic" if trace_id else "no trace"}

    todo = todo_service.get_todo(user_id, trace_id)
    if todo is None:
        return {"status": "skip", "reason": "no todo"}
    if todo.status != "active":
        # An explicit awaiting by the session (or any other non-active state)
        # wins; it already notified.
        return {"status": "skip", "reason": "not active"}

    try:
        return await _reconcile_active(user_id, todo)
    except Exception:
        logger.exception("session_end: reconcile failed: user_id={}", user_id)
        return {"status": "failed"}


async def _reconcile_active(user_id: int, todo) -> dict:
    # Probe time T bounds every claim: only evidence observed at or after it
    # can prove this turn's trace ended.
    observed_at = get_unix_timestamp()
    jobs = await probe_owner(user_id)
    try:
        upsert_snapshot(user_id, observed_at, ok=jobs is not None, jobs=jobs or {})
    except Exception:
        logger.exception("session_end: snapshot write failed: user_id={}", user_id)

    result = claim_idle_trace(user_id, todo, REASON, observed_at)
    return {
        "status": "ok",
        "outcome": result["outcome"],
        "evidence": result["evidence"],
        "runtime_state": result["runtime_state"],
    }
