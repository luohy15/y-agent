"""Orchestrates the live subscription limit-window read (Claude, Codex, Grok)
that backs the persisted snapshot: resolve the user's VM, SSH-exec
`y usage limits --json` (mirroring worker/downloaders/ssh.py), and normalize
the result via storage.service.model_usage_limits. Lives in `agent` (not
`storage`) because it needs agent.tool_base / agent.ec2_wake, and storage
must not depend on agent (agent already depends on storage).

todo 3226: ordinary `GET /api/usage/limits` reads no longer land here at all
— they read the persisted snapshot directly (storage.service.model_usage_
limits.read_snapshot). This module now exists only to *produce* that
snapshot: `refresh_and_persist_snapshot` is the one refresh function shared
by the worker's five-minute scheduled sweep and the explicit `?refresh=true`
API retry. Each call is guarded by a per-user pipeline lock
(`refresh_usage_limits:<user_id>`) so the sweep and a manual retry — or two
manual retries — can never launch overlapping CLI runs for the same user. A
failed attempt (VM asleep, SSH/CLI error, malformed payload) never discards
the last successful provider data; storage.read_snapshot re-derives freshness
from each row's own observed_at on every read, so retained old data goes
stale on its own rather than being force-marked at write time.

Refresh is owner-scoped: the VM is this user's own `default` config
(`resolve_usage_vm_config`), never the global default user's, and
`list_refresh_user_ids` is the sweep's eligibility rule. Every blocking DB /
boto3 call on these paths is dispatched with this module's `offload` (see
below) so it cannot stall the caller's event loop and therefore cannot
defeat the caller's own timeout; the same is true of `ssh_exec`'s wake/touch
prelude underneath the CLI call. `list_refresh_user_ids` is sync and its
caller offloads it.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from agent.ec2_wake import is_vm_asleep
from agent.tool_base import Tool
from storage.database.base import statement_timeout
from storage.service import model_usage_limits as limits
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import vm_config as vm_service
from storage.util import get_utc_iso8601_timestamp

# --- off-loop dispatch for this module's bookkeeping ---------------------
#
# The DB and EC2 calls below run in a thread rather than on the caller's event
# loop: on the loop they freeze it, and a frozen loop cannot deliver the
# `asyncio.wait_for` timeout the scheduled sweep bounds each user with (todo
# 3226). Two things about this executor are deliberate.
#
# It is not the loop's default executor, because `asyncio.run()`'s teardown
# awaits `loop.shutdown_default_executor()`: an abandoned default-executor
# thread would add its remaining runtime straight back onto
# `worker/handler.py`'s scheduled invocation, i.e. the 900s Lambda timeout
# this work exists to remove, reached by another route.
#
# It is not shared with `agent.tools.ssh_exec`'s executor either. That pool
# serves every SSH caller in the process; sharing one saturable pool between
# it and this bookkeeping would let either side delay the other, including
# the lock release below, which is the one call a cancelled attempt still
# depends on.
#
# What it does not provide: a running thread cannot be cancelled. A call
# whose awaiter timed out keeps going until the operation itself ends, still
# holding what it holds (a pooled DB connection and its transaction, an
# already-acquired pipeline lock whose commit lands after the attempt was
# reported timed out), and a *graceful* interpreter exit joins it —
# `concurrent.futures.thread` registers an exit hook that joins non-daemon
# workers, so "the container gets recycled" only reclaims it when the process
# is killed outright. That is why the real bound lives in the operations
# themselves and not in this pool or in the caller: a connect timeout, TCP
# keepalives and a bounded pool checkout in `storage.database.base` plus the
# per-workload `statement_timeout` this module opts into below; botocore
# timeouts in `agent.ec2_wake`; socket timeouts plus force-close in
# `ssh_exec`. Callers here therefore do not need a timeout of their own to
# keep the pool healthy (several, such as an ordinary `read_snapshot`, have
# none) — threads come back because the operations end.
#
# Comfortably below the sweep's 45s per-user cap, so a stalled statement
# releases its thread and its pooled connection before the next tick could
# need them, and far above any statement on this path (single-row reads and
# writes keyed by user, plus one indexed eligibility query).
_DB_STATEMENT_TIMEOUT_SECONDS = 30.0

# Sized for the worst case the scheduled sweep can present: its eight
# concurrent attempts, each with at most one call in flight plus (when it was
# cancelled mid-call) its lock release. Nothing queues in normal operation.
_MAX_WORKERS = 16

_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="usage-limits")


async def offload(func, *args, **kwargs):
    """`asyncio.to_thread` semantics on this module's executor, with every
    statement the call issues bounded server-side.

    The timeout is opted into here rather than set on the engine because it
    is a claim about *these* calls: single-row reads and writes keyed by
    user, plus the sweep's one indexed eligibility query, all orders of
    magnitude below the bound, so anything reaching it is a stall. It is
    applied inside the worker thread because that is where the queries run
    and where the context lives (`run_in_executor` does not carry the
    caller's context across).
    """
    def _run_bounded():
        with statement_timeout(_DB_STATEMENT_TIMEOUT_SECONDS):
            return func(*args, **kwargs)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, _run_bounded)


_CLI_TIMEOUT_SECONDS = 30.0

# The guarded work is bounded at ~_CLI_TIMEOUT_SECONDS; pipeline_lock's own
# default (840s) would leave a user locked out of both the sweep and a manual
# refresh for up to 14 minutes if a worker invocation died before `finally`
# ran. 120s bounds that to one or two missed five-minute ticks instead, while
# still comfortably covering the CLI timeout plus SSH/connect overhead.
_LOCK_TTL_SECONDS = 120

# Releasing the lock is the last thing a cancelled attempt does, so it must
# not become a way for the attempt (and with it the sweep's run budget) to
# stay open: past this bound the release is left to the TTL above.
_LOCK_RELEASE_TIMEOUT_SECONDS = 5.0

# Stable per-provider/errors[] error codes. Raw exception text is never
# surfaced to a caller-facing field (BotViewer renders `error` verbatim); it
# only ever reaches logger.warning.
_ERROR_VM_UNREACHABLE = "vm_unreachable"
_ERROR_CLI_FAILED = "cli_failed"
_ERROR_BAD_PAYLOAD = "bad_payload"
_ERROR_NO_USAGE_VM = "no_usage_vm"

# The VM config name a subscription-limit read runs on.
USAGE_VM_NAME = "default"


def resolve_usage_vm_config(user_id: int):
    """This user's *own* usage VM, or None when they have not configured one.

    Deliberately not `agent.config.resolve_vm_config`: that falls back to the
    global default user's VM, which is right for interactive dispatch but
    wrong here twice over. A subscription-limit read runs `y usage limits` on
    the VM and reports *that machine's* provider logins, so borrowing another
    account's VM would attribute someone else's subscription status to this
    user; and in production the inherited fallback pointed at a dead host, so
    every user without their own config burned an SSH connect timeout per
    sweep (todo 3226).
    """
    return vm_service.get_config(user_id, USAGE_VM_NAME)


def list_refresh_user_ids() -> list[int]:
    """The users the scheduled sweep may refresh: exactly those who own a
    usage VM config. Explicit and owner-scoped, in one query, so the sweep
    never probes a user who would only inherit the global fallback."""
    return sorted(vm_service.list_user_ids_with_config(USAGE_VM_NAME))


def _lock_name(user_id: int) -> str:
    return f"refresh_usage_limits:{user_id}"


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def _run_usage_limits_cli(vm_config, refresh: bool = False) -> str:
    """Run `y usage limits --json` on the user's VM and return raw stdout.
    `refresh` appends `--refresh`, telling the CLI to bypass its own on-VM
    cache for this one read."""
    cmd = ["y", "usage", "limits", "--json"]
    if refresh:
        cmd.append("--refresh")
    runner = _CmdRunner(vm_config)
    return await runner.run_cmd(cmd, timeout=_CLI_TIMEOUT_SECONDS)


def _error_code(e: Exception) -> str:
    """Map a CLI-read exception to a stable, enumerable code. Full detail
    stays in logger.warning; only the code reaches provider.error / errors[]."""
    if isinstance(e, json.JSONDecodeError):
        return _ERROR_BAD_PAYLOAD
    return _ERROR_CLI_FAILED


async def _record_failure(user_id: int, error_code: str, attempt_at: str) -> dict:
    return await offload(limits.record_refresh_failure, user_id, error_code, attempt_at)


async def refresh_and_persist_snapshot(user_id: int, force: bool = False) -> dict | None:
    """The one refresh function shared by the five-minute scheduled worker
    sweep and the explicit `?refresh=true` API path. Acquires this user's
    pipeline lock so the sweep and a manual retry (or two manual retries)
    never overlap; returns None when the lock is already held, so the caller
    decides how to react — skip for the sweep, serve the stored snapshot for
    a manual request — instead of starting a second CLI run.

    The VM is resolved owner-scoped (`resolve_usage_vm_config`): a user with
    no VM config of their own answers `no_usage_vm` immediately rather than
    running the CLI on the global default user's VM.

    Every blocking dependency here — the lock calls, the owner lookup, the
    EC2 state probe, and snapshot persistence — runs through this module's
    `offload`, so a caller's timeout can actually fire: none of them may
    occupy the event loop (shared, in the sweep, with every other user's
    attempt and the run deadline itself). Cancellation abandons such a
    thread rather than killing it, so what keeps the pool healthy is that
    each of those operations is independently bounded and cleans up after
    itself (see the executor comment above), not the cancellation.

    `force` maps to the CLI's own `--refresh` flag (bypass its on-VM cache):
    True only for the explicit user retry, False for the scheduled sweep,
    which runs slower than that cache's own TTL and does not need to force
    it. A stopped EC2 instance is never woken to serve a refresh; it answers
    `vm_unreachable` immediately, same as an ordinary SSH/CLI failure.
    """
    lock_name = _lock_name(user_id)
    if not await offload(
        pipeline_lock_service.try_acquire_lock, lock_name, ttl_seconds=_LOCK_TTL_SECONDS
    ):
        return None

    attempt_at = get_utc_iso8601_timestamp()
    try:
        try:
            vm_config = await offload(resolve_usage_vm_config, user_id)
            if vm_config is None:
                return await _record_failure(user_id, _ERROR_NO_USAGE_VM, attempt_at)
            if await offload(is_vm_asleep, vm_config):
                return await _record_failure(user_id, _ERROR_VM_UNREACHABLE, attempt_at)
            output = await _run_usage_limits_cli(vm_config, refresh=force)
            raw = json.loads(output.strip())
        except Exception as e:
            logger.warning("refresh_and_persist_snapshot: CLI read failed for user {}: {}", user_id, e)
            return await _record_failure(user_id, _error_code(e), attempt_at)

        envelope = limits.normalize_envelope(raw, limits.DEFAULT_TTL_SECONDS)
        if not envelope["providers"] and envelope["errors"]:
            # A well-formed-JSON-but-wrong-shape payload (or an envelope
            # whose every item was malformed) is not a structurally valid
            # attempt — treat it like a CLI exception rather than persisting
            # a providers-less snapshot that would blank an otherwise-good
            # card.
            error_code = envelope["errors"][0].get("error") or _ERROR_BAD_PAYLOAD
            return await _record_failure(user_id, error_code, attempt_at)

        return await offload(limits.record_refresh_success, user_id, envelope, attempt_at)
    finally:
        # Shielded *and* bounded, in that order. Shielded because the caller's
        # timeout (the sweep cancels an attempt that outlives its per-user
        # cap) would otherwise interrupt the release too and leave this user
        # locked out for the whole _LOCK_TTL_SECONDS. Bounded because the
        # cancellation path must not be able to hold the attempt open for
        # longer than the cap it was cancelled by — the sweep's per-user
        # bound has to survive a slow release, not depend on it. If the bound
        # fires (or the loop is torn down first) the TTL is the backstop and
        # the user is skipped for at most one tick.
        try:
            await asyncio.shield(
                asyncio.wait_for(
                    offload(pipeline_lock_service.release_lock, lock_name),
                    timeout=_LOCK_RELEASE_TIMEOUT_SECONDS,
                )
            )
        except asyncio.TimeoutError:
            logger.warning(
                "refresh_and_persist_snapshot: lock release timed out for user {}", user_id
            )


async def get_limit_status(user_id: int, refresh: bool = False) -> dict:
    """`GET /api/usage/limits` read path. An ordinary poll (`refresh=False`)
    only reads the persisted snapshot: preference lookup plus freshness
    normalization, never VM/SSH/CLI — the five-minute worker sweep is what
    keeps it current. `refresh=True` is an explicit user-initiated retry: it
    runs one bounded refresh through the same function the sweep uses and
    returns the resulting snapshot; if another refresh already owns this
    user's lock, it returns the stored snapshot immediately with
    `refresh_in_progress` set instead of queuing a second overlapping CLI
    run.
    """
    if not refresh:
        return await offload(limits.read_snapshot, user_id)

    result = await refresh_and_persist_snapshot(user_id, force=True)
    if result is None:
        stored = await offload(limits.read_snapshot, user_id)
        return {**stored, "refresh_in_progress": True}
    return result
