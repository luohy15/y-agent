"""Shared runtime-evidence derivation (todo 4070).

Display and the trace-liveness watchdog derive from the same inputs: the
trace's chat evidence plus the owner's last probe snapshot. "Unknown" or stale
evidence proves neither running nor ended, so it never lets the watchdog claim
a fault, and the display says so.
"""

from typing import Optional

# A snapshot older than this cannot prove "ended" for display or the watchdog.
RUNTIME_FRESH_MS = 600_000


def _payload(state: str, jobs=(), observed_at_unix: Optional[int] = None,
             fresh_until_unix: Optional[int] = None) -> dict:
    return {
        "state": state,
        "jobs": list(jobs),
        "observed_at_unix": observed_at_unix,
        "fresh_until_unix": fresh_until_unix,
    }


def _valid_observed(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_jobs(value):
    """A job map is `{todo_id: [non-empty session names]}`; anything else is unknown."""
    if not isinstance(value, dict):
        return None
    for names in value.values():
        if not isinstance(names, list) or not names:
            return None
        if not all(isinstance(name, str) and name for name in names):
            return None
    return value


def derive_runtime(roles, snapshot, todo_id: str, now_ms: int,
                   observed_after_ms: Optional[int] = None) -> dict:
    """One active todo's runtime evidence.

    `roles` is `(chat_count, running_role, running_roleless, role_chats)`.
    A running role chat is the session; a running role-less chat is a child
    when the trace also has a role chat, otherwise it is the session itself.
    With no running chat, only a valid, fresh snapshot can say `tmux` or
    `ended`; everything else is `unknown`.
    """
    _chat_count, running_role, running_roleless, role_chats = roles or (0, 0, 0, 0)
    if running_role > 0:
        return _payload("session")
    if running_roleless > 0:
        return _payload("child" if role_chats > 0 else "session")

    snap = snapshot if isinstance(snapshot, dict) else {}
    observed = snap.get("observed_at_unix")
    if not _valid_observed(observed) or observed > now_ms:
        observed = None
    jobs = _valid_jobs(snap.get("jobs"))

    fresh = (
        snap.get("ok") is True
        and observed is not None
        and jobs is not None
        and now_ms - observed <= RUNTIME_FRESH_MS
        and (observed_after_ms is None or observed >= observed_after_ms)
    )
    if not fresh:
        return _payload("unknown", observed_at_unix=observed)

    fresh_until = observed + RUNTIME_FRESH_MS
    names = jobs.get(todo_id)
    if names:
        return _payload("tmux", sorted(names), observed, fresh_until)
    return _payload("ended", (), observed, fresh_until)
