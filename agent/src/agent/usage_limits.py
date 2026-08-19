"""Orchestrates the live subscription limit-window read (Claude, Codex, Grok)
that backs the persisted snapshot: resolve the user's VM, SSH-exec
`y usage limits --json` (mirroring worker/downloaders/ssh.py), and normalize
the result via storage.service.model_usage_limits. Lives in `agent` (not
`storage`) because it needs agent.config / agent.tool_base / agent.ec2_wake,
and storage must not depend on agent (agent already depends on storage).

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
"""

import json

from loguru import logger

from agent.config import resolve_vm_config
from agent.ec2_wake import is_vm_asleep
from agent.tool_base import Tool
from storage.service import model_usage_limits as limits
from storage.service import pipeline_lock as pipeline_lock_service
from storage.util import get_utc_iso8601_timestamp

_CLI_TIMEOUT_SECONDS = 30.0

# The guarded work is bounded at ~_CLI_TIMEOUT_SECONDS; pipeline_lock's own
# default (840s) would leave a user locked out of both the sweep and a manual
# refresh for up to 14 minutes if a worker invocation died before `finally`
# ran. 120s bounds that to one or two missed five-minute ticks instead, while
# still comfortably covering the CLI timeout plus SSH/connect overhead.
_LOCK_TTL_SECONDS = 120

# Stable per-provider/errors[] error codes. Raw exception text is never
# surfaced to a caller-facing field (BotViewer renders `error` verbatim); it
# only ever reaches logger.warning.
_ERROR_VM_UNREACHABLE = "vm_unreachable"
_ERROR_CLI_FAILED = "cli_failed"
_ERROR_BAD_PAYLOAD = "bad_payload"


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


async def refresh_and_persist_snapshot(user_id: int, force: bool = False) -> dict | None:
    """The one refresh function shared by the five-minute scheduled worker
    sweep and the explicit `?refresh=true` API path. Acquires this user's
    pipeline lock so the sweep and a manual retry (or two manual retries)
    never overlap; returns None when the lock is already held, so the caller
    decides how to react — skip for the sweep, serve the stored snapshot for
    a manual request — instead of starting a second CLI run.

    `force` maps to the CLI's own `--refresh` flag (bypass its on-VM cache):
    True only for the explicit user retry, False for the scheduled sweep,
    which runs slower than that cache's own TTL and does not need to force
    it. A stopped EC2 instance is never woken to serve a refresh; it answers
    `vm_unreachable` immediately, same as an ordinary SSH/CLI failure.
    """
    lock_name = _lock_name(user_id)
    if not pipeline_lock_service.try_acquire_lock(lock_name, ttl_seconds=_LOCK_TTL_SECONDS):
        return None

    attempt_at = get_utc_iso8601_timestamp()
    try:
        try:
            vm_config = resolve_vm_config(user_id)
            if is_vm_asleep(vm_config):
                return limits.record_refresh_failure(user_id, _ERROR_VM_UNREACHABLE, attempt_at)
            output = await _run_usage_limits_cli(vm_config, refresh=force)
            raw = json.loads(output.strip())
        except Exception as e:
            logger.warning("refresh_and_persist_snapshot: CLI read failed for user {}: {}", user_id, e)
            return limits.record_refresh_failure(user_id, _error_code(e), attempt_at)

        envelope = limits.normalize_envelope(raw, limits.DEFAULT_TTL_SECONDS)
        if not envelope["providers"] and envelope["errors"]:
            # A well-formed-JSON-but-wrong-shape payload (or an envelope
            # whose every item was malformed) is not a structurally valid
            # attempt — treat it like a CLI exception rather than persisting
            # a providers-less snapshot that would blank an otherwise-good
            # card.
            error_code = envelope["errors"][0].get("error") or _ERROR_BAD_PAYLOAD
            return limits.record_refresh_failure(user_id, error_code, attempt_at)

        return limits.record_refresh_success(user_id, envelope, attempt_at)
    finally:
        pipeline_lock_service.release_lock(lock_name)


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
        return limits.read_snapshot(user_id)

    result = await refresh_and_persist_snapshot(user_id, force=True)
    if result is None:
        return {**limits.read_snapshot(user_id), "refresh_in_progress": True}
    return result
