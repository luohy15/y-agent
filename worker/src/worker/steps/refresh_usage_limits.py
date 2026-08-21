"""Scheduled action: refresh the persisted subscription limit-window snapshot
(`user_preference` key `usage_limits_latest`) of every *eligible* user, so
ordinary `GET /api/usage/limits` reads never touch the VM/SSH/CLI path
(todo 3226).

Eligibility is explicit and owner-scoped (`agent.usage_limits.
list_refresh_user_ids`): only users who own a `default` VM config are swept.
The first version walked every active user through the general
`resolve_vm_config`, which silently inherits the global default user's VM, so
in production ~123 users without a config of their own each burned ~15s on an
SSH connect timeout against a dead host and the one real user (position 111
of 124) was never reached before the 900s Lambda timeout — with a five-minute
cadence that meant permanently overlapping invocations and a snapshot that
never advanced. Diagnosis:
pages/plan-3226-usage-limits-refresh-production-defect.md.

Coverage, stated exactly: one run attempts every eligible user within the
schedule interval **as long as the eligible set fits one run's guaranteed
capacity** (`_guaranteed_capacity()` = `_MAX_CONCURRENCY` slots ×
`_attempt_budget() // _USER_TIMEOUT_SECONDS` serial attempts per slot = 32
today, against 2 eligible users in production), even in the worst case where
every attempt burns its full per-user cap. Above that capacity there is no
same-interval guarantee: the run attempts as many users as fit, reports the
rest as `deadline`, logs a warning that the guarantee no longer holds, and
`_rotate_for_fairness` only makes coverage *eventual* — a set of N users
needs about `ceil(N / capacity)` ticks. That weaker mode is a signal to raise
the capacity, not a design the sweep relies on.

The bounds are real only because of three things together. First, no
blocking call sits on the event loop: `agent.usage_limits.
refresh_and_persist_snapshot` dispatches its DB and EC2 work off it (as does
`ssh_exec`'s wake/touch prelude), and the eligibility query here is offloaded
and separately bounded, because `asyncio.wait_for` can cancel an attempt only
when control returns to the loop. Second, that offloading goes to
module-owned executors rather than the loop's default one, which
`asyncio.run` teardown joins (`Runner.close()` awaits
`loop.shutdown_default_executor()`): an abandoned default-executor thread
would keep `worker/handler.py`'s `asyncio.run(handle_refresh_usage_limits())`
inside the invocation long after the sweep reported a tidy timeout — the same
900s Lambda timeout this step exists to prevent, reached by a different
route. Third — since no thread can be cancelled, and an executor is therefore
only event-loop isolation, never a bound — every operation those threads run
is bounded and cleaned up at its own layer: connect/statement/keepalive
timeouts and a bounded pool checkout in `storage.database.base`, botocore
timeouts and bounded waits in `agent.ec2_wake`, socket timeouts plus
force-close in `ssh_exec`, and a bounded lock release in
`refresh_and_persist_snapshot` so a cancelled attempt cannot stay open behind
its own cleanup.

Each attempt still calls the same `refresh_and_persist_snapshot` the explicit
`?refresh=true` API path uses, still un-forced, and still takes that user's
own `refresh_usage_limits:<user_id>` pipeline lock, so a user whose previous
sweep (or a concurrent manual refresh) is still running is skipped for this
tick rather than doubled up.

Observability is one bounded line per user plus one completion summary per
run. Both outcome and reason come from closed vocabularies (`_OUTCOMES`, and
`ERROR_CODES` for anything read back out of a snapshot); anything else
collapses to `_REASON_UNRECOGNIZED`. No payload, credential, or exception
detail is emitted from this path.
"""

import asyncio
import time

from loguru import logger

from agent.usage_limits import list_refresh_user_ids, offload, refresh_and_persist_snapshot
from storage.service.model_usage_limits import ERROR_CODES

# At most this many users are read concurrently. Each attempt is an SSH
# round-trip that spends nearly all its time waiting, so the ceiling is about
# bounding sockets and executor threads (paramiko runs on ssh_exec's own
# executor, the DB/EC2 bookkeeping on agent.usage_limits', and both are sized
# against this number), not CPU.
_MAX_CONCURRENCY = 8

# Per-user cap. Comfortably above agent.usage_limits._CLI_TIMEOUT_SECONDS
# (30s) plus connect overhead, so this only fires when a user is stuck past
# the point the transport itself should have given up — one such user must
# not consume the run's budget.
_USER_TIMEOUT_SECONDS = 45.0

# rate(5 minutes), from template.yaml's RefreshUsageLimitsSchedule. Not read
# from the event: the schedule is the contract, and the sweep only needs it to
# size its own budget and its fairness rotation.
_SCHEDULE_INTERVAL_SECONDS = 300

# Whole-run budget for the handler, end to end: eligibility, every attempt,
# and bookkeeping. A tick always ends before the next one starts (no
# accumulation) and far inside the 900s Lambda timeout.
_RUN_BUDGET_SECONDS = 240.0

# The eligibility query runs before any attempt and must not become the one
# unbounded step in a step that is all about bounds.
_ELIGIBILITY_TIMEOUT_SECONDS = 15.0

# Conservative allowance for everything that is neither the eligibility query
# nor an attempt: task setup, the gather, counting, logging, and the return.
_OVERHEAD_SECONDS = 5.0

# Closed per-user outcome vocabulary.
_OUTCOME_OK = "ok"              # attempt succeeded, every provider row clean
_OUTCOME_PARTIAL = "partial"    # attempt succeeded, some provider read failed
_OUTCOME_FAILED = "failed"      # attempt failed as a whole (envelope level)
_OUTCOME_LOCKED = "locked"      # another refresh owns this user's lock
_OUTCOME_TIMEOUT = "timeout"    # attempt exceeded _USER_TIMEOUT_SECONDS
_OUTCOME_DEADLINE = "deadline"  # run budget spent before this user started
_OUTCOME_ERROR = "error"        # unhandled exception

_OUTCOMES = (
    _OUTCOME_OK,
    _OUTCOME_PARTIAL,
    _OUTCOME_FAILED,
    _OUTCOME_LOCKED,
    _OUTCOME_TIMEOUT,
    _OUTCOME_DEADLINE,
    _OUTCOME_ERROR,
)

# A snapshot's own error strings are supposed to come from ERROR_CODES, but
# they arrive here through normalize_envelope, which copies the VM CLI's
# `errors[]` entries unchanged. Anything unrecognized becomes this one code
# rather than putting an arbitrary string in an operational log line.
_REASON_UNRECOGNIZED = "unrecognized"

# Whole-run failure reason (the summary's `reason`, not a per-user one).
_REASON_ELIGIBILITY_TIMEOUT = "eligibility_timeout"


def _attempt_budget() -> float:
    """The wall clock actually available to attempts.

    Not `_RUN_BUDGET_SECONDS`: the eligibility query may consume its whole
    allowance before the first attempt starts, and the run still has to count,
    log and return afterwards. Charging both to the attempt phase up front is
    what keeps the *handler's* budget honest, and it is the same number the
    attempt deadline is built from, so capacity and deadline cannot drift.
    The overhead allowance also covers the last attempt's bounded lock-release
    tail (`_LOCK_RELEASE_TIMEOUT_SECONDS`), which is the only work that can
    run past the attempt deadline.
    """
    return _RUN_BUDGET_SECONDS - _ELIGIBILITY_TIMEOUT_SECONDS - _OVERHEAD_SECONDS


def _guaranteed_capacity() -> int:
    """How many eligible users one run is guaranteed to attempt, worst case.

    Every slot can run `_attempt_budget() // _USER_TIMEOUT_SECONDS` attempts
    back to back even if each one burns its full cap, and no attempt starts
    with less than a full cap left, so the product is a floor rather than an
    estimate (32 at today's constants). Above it the sweep loses its
    same-interval coverage guarantee and says so (see
    `handle_refresh_usage_limits`).
    """
    return _MAX_CONCURRENCY * int(_attempt_budget() // _USER_TIMEOUT_SECONDS)


def _rotate_for_fairness(user_ids: list[int]) -> list[int]:
    """Rotate the eligible list by one position per schedule tick.

    A no-op reordering while the eligible set fits `_guaranteed_capacity()`,
    which is the only regime with a same-interval guarantee. It exists for the
    over-capacity regime, where it degrades coverage to *eventual* instead of
    permanent starvation of the tail — the defect this change fixes was
    precisely a fixed-order walk whose tail was never reached.
    """
    if not user_ids:
        return user_ids
    offset = int(time.time() // _SCHEDULE_INTERVAL_SECONDS) % len(user_ids)
    return user_ids[offset:] + user_ids[:offset]


def _reason_code(value) -> str:
    """Collapse anything outside the closed error vocabulary to one code."""
    return value if isinstance(value, str) and value in ERROR_CODES else _REASON_UNRECOGNIZED


def _first_error_code(snapshot: dict) -> str | None:
    """The first error reported by an otherwise *successful* attempt, if any:
    an envelope-level entry, else a provider row that carries one. Returned as
    a bounded code, never as whatever string the payload held."""
    for entry in snapshot.get("errors") or []:
        if entry.get("error"):
            return _reason_code(entry.get("error"))
    for provider in snapshot.get("providers") or []:
        if provider.get("error"):
            return _reason_code(provider.get("error"))
    return None


def _classify(snapshot: dict | None) -> tuple[str, str]:
    """Map one refresh result to (outcome, reason), both bounded codes."""
    if snapshot is None:
        return _OUTCOME_LOCKED, _OUTCOME_LOCKED
    if snapshot.get("last_attempt_status") != "ok":
        return _OUTCOME_FAILED, _reason_code(snapshot.get("last_attempt_error"))
    partial = _first_error_code(snapshot)
    if partial:
        return _OUTCOME_PARTIAL, partial
    return _OUTCOME_OK, _OUTCOME_OK


async def _refresh_one(user_id: int, deadline: float, semaphore: asyncio.Semaphore) -> tuple[str, str]:
    async with semaphore:
        if deadline - time.monotonic() < _USER_TIMEOUT_SECONDS:
            # Never start an attempt that cannot have its full cap: it would
            # report a `timeout` it never really got, and would push the run
            # past its budget. Within capacity this branch is unreachable.
            return _OUTCOME_DEADLINE, _OUTCOME_DEADLINE
        started = time.monotonic()
        try:
            snapshot = await asyncio.wait_for(
                refresh_and_persist_snapshot(user_id, force=False),
                timeout=_USER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            outcome, reason = _OUTCOME_TIMEOUT, _OUTCOME_TIMEOUT
        except Exception:
            # Deliberately no exception detail: this line is an operational
            # signal with a closed vocabulary, and the layer that raised
            # already logs its own diagnostics.
            outcome, reason = _OUTCOME_ERROR, _OUTCOME_ERROR
        else:
            outcome, reason = _classify(snapshot)
        logger.info(
            "refresh_usage_limits: user_id={} outcome={} reason={} duration_ms={}",
            user_id, outcome, reason, int((time.monotonic() - started) * 1000),
        )
        return outcome, reason


def _summary(user_ids: list[int], counts: dict, started: float, reason: str | None = None) -> dict:
    result = {
        "status": "error" if reason else "ok",
        "action": "refresh_usage_limits",
        "eligible": len(user_ids),
        **{name: counts[name] for name in _OUTCOMES},
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if reason:
        result["reason"] = reason
    return result


async def handle_refresh_usage_limits() -> dict:
    started = time.monotonic()
    counts = {name: 0 for name in _OUTCOMES}

    try:
        user_ids = await asyncio.wait_for(
            offload(list_refresh_user_ids), timeout=_ELIGIBILITY_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning(
            "refresh_usage_limits: eligible=? reason={} after {}s",
            _REASON_ELIGIBILITY_TIMEOUT, _ELIGIBILITY_TIMEOUT_SECONDS,
        )
        return _summary([], counts, started, reason=_REASON_ELIGIBILITY_TIMEOUT)

    # The attempt deadline is established *here*, after eligibility, from a
    # budget that already excludes the eligibility allowance and the run's
    # own overhead — so the handler stays inside _RUN_BUDGET_SECONDS however
    # long the query actually took.
    deadline = time.monotonic() + _attempt_budget()
    user_ids = _rotate_for_fairness(user_ids)
    capacity = _guaranteed_capacity()
    if len(user_ids) > capacity:
        logger.warning(
            "refresh_usage_limits: eligible={} exceeds one run's guaranteed capacity={}; "
            "same-interval coverage no longer holds, the remainder rotates to later ticks",
            len(user_ids), capacity,
        )

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    outcomes = await asyncio.gather(
        *(_refresh_one(user_id, deadline, semaphore) for user_id in user_ids)
    )
    for outcome, _reason in outcomes:
        counts[outcome] += 1

    summary = _summary(user_ids, counts, started)
    logger.info(
        "refresh_usage_limits: eligible={} capacity={} ok={} partial={} failed={} locked={} "
        "timeout={} deadline={} error={} duration_ms={}",
        len(user_ids), capacity,
        counts[_OUTCOME_OK], counts[_OUTCOME_PARTIAL], counts[_OUTCOME_FAILED],
        counts[_OUTCOME_LOCKED], counts[_OUTCOME_TIMEOUT], counts[_OUTCOME_DEADLINE],
        counts[_OUTCOME_ERROR], summary["duration_ms"],
    )
    return summary
