"""Normal-session-end trace reconcile (todo 4077).

When a Claude Code turn closes out normally, the worker probes the owner's
default VM once, stores that snapshot like the scheduled refresher does, and
runs the same under-lock idle claim the trace-liveness watchdog uses. If
nothing else can advance the trace, the todo moves `active -> awaiting`
immediately instead of waiting for the next watchdog tick, and a durable
`trace_session_end` row records what happened. The watchdog stays the
abnormal-recovery fallback; this path never completes a todo and never writes
progress.

Every failure is logged and swallowed so the turn's closeout never depends on
it.
"""

from typing import Optional

from loguru import logger

from storage.repository import trace_session_end as disposition_repo
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


def _record(user_id: int, chat_id: str, trace_id: str, run_key: str, disposition: str,
            evidence: Optional[str], observed_at_unix: Optional[int],
            ended_at_unix: int) -> None:
    """Best-effort disposition write; a missing table or failure only logs."""
    try:
        disposition_repo.insert_disposition(
            user_id, chat_id, trace_id, run_key,
            disposition=disposition, evidence=evidence,
            runtime_observed_at_unix=observed_at_unix, ended_at_unix=ended_at_unix,
        )
    except Exception:
        logger.exception(
            "session_end: disposition write failed: user_id={} chat_id={} run_key={}",
            user_id, chat_id, run_key,
        )


async def reconcile_session_end(user_id: int, chat, proc: dict) -> dict:
    """Reconcile one normally completed turn's trace. Never raises."""
    trace_id = (chat.trace_id or "").strip()
    run_key = str(proc.get("started_at") or "")
    if not should_reconcile(chat):
        return {"status": "skip", "reason": "root topic" if trace_id else "no trace"}

    ended_at = get_unix_timestamp()
    todo = todo_service.get_todo(user_id, trace_id)
    if todo is None:
        return {"status": "skip", "reason": "no todo"}
    if todo.status != "active":
        # An explicit awaiting by the session (or any other non-active state)
        # wins; it already notified.
        _record(user_id, chat.id, trace_id, run_key, "not_active", None, None, ended_at)
        return {"status": "skip", "reason": "not active", "disposition": "not_active"}

    try:
        return await _reconcile_active(user_id, chat.id, trace_id, run_key, todo, ended_at)
    except Exception:
        logger.exception(
            "session_end: reconcile failed: user_id={} chat_id={} run_key={}",
            user_id, chat.id, run_key,
        )
        _record(user_id, chat.id, trace_id, run_key, "failed", None, None, ended_at)
        return {"status": "failed"}


async def _reconcile_active(user_id: int, chat_id: str, trace_id: str, run_key: str,
                            todo, ended_at: int) -> dict:
    # Probe time T bounds every claim: only evidence observed at or after it
    # can prove this turn's trace ended.
    observed_at = get_unix_timestamp()
    jobs = await probe_owner(user_id)
    try:
        upsert_snapshot(user_id, observed_at, ok=jobs is not None, jobs=jobs or {})
    except Exception:
        logger.exception("session_end: snapshot write failed: user_id={}", user_id)

    result = claim_idle_trace(user_id, todo, REASON, observed_at)
    outcome, evidence = result["outcome"], result["evidence"]

    if outcome == "claimed":
        disposition = "awaiting"
        evidence = None
    elif outcome == "failed":
        disposition = "failed"
    elif not result["rechecked"]:
        # The row was no longer ours to claim: either it left `active`
        # concurrently (not_active) or only its timestamp moved (stale).
        current = todo_service.get_todo(user_id, trace_id)
        if current is not None and current.status != "active":
            disposition = "not_active"
        else:
            disposition, evidence = "active", "stale_row"
    elif result["runtime_state"] == "unknown":
        disposition, evidence = "unknown", None
    else:
        # `ended` with a named suppressor, or ended but the classifier no
        # longer applies. Either way the trace stays active.
        disposition = "active"

    _record(user_id, chat_id, trace_id, run_key, disposition, evidence, observed_at, ended_at)
    return {"status": "ok", "disposition": disposition, "evidence": evidence}
