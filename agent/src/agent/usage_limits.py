"""Orchestrates a live subscription limit-window read: resolve the user's VM,
SSH-exec `y usage limits --json` (mirroring worker/downloaders/ssh.py), and
normalize the result via storage.service.model_usage_limits. Lives in `agent`
(not `storage`) because it needs agent.config / agent.tool_base / agent.ec2_wake,
and storage must not depend on agent (agent already depends on storage).

A per-user in-process TTL memo (~60s) collapses a burst of 60s-cadence panel
polls into one SSH round trip; a transient SSH/CLI failure serves the
last-good snapshot as `stale` rather than blanking the card; a stopped EC2
instance is never woken just to answer a poll — it answers `vm_unreachable`
immediately. `refresh=True` (an explicit user retry, not the automatic poll)
bypasses the memo and passes `--refresh` through to the CLI, which owns a
longer-TTL on-VM cache for the scrape-backed Anthropic reader (todo 2515) that
an in-process memo can't reach since the CLI is a fresh process per invocation.
"""

import json
import os
import time
from dataclasses import dataclass

from loguru import logger

from agent.config import resolve_vm_config
from agent.ec2_wake import is_vm_asleep
from agent.tool_base import Tool
from storage.service import model_usage_limits as limits

# Poll-cost guard: separate from limits.DEFAULT_TTL_SECONDS, which governs
# fresh/stale freshness classification of a single reading. The CLI's own
# on-VM cache (owned CLI-side) covers the slower scrape-backed reader with a
# longer TTL; this memo only needs to cover the two cheap HTTP readers.
POLL_TTL_SECONDS = int(os.getenv("USAGE_LIMIT_POLL_TTL_SECONDS", "60"))

_CLI_TIMEOUT_SECONDS = 30.0

# Stable per-provider/errors[] error codes. Raw exception text is never
# surfaced to a caller-facing field (BotViewer renders `error` verbatim); it
# only ever reaches logger.warning.
_ERROR_VM_UNREACHABLE = "vm_unreachable"
_ERROR_CLI_FAILED = "cli_failed"
_ERROR_BAD_PAYLOAD = "bad_payload"


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


@dataclass
class _CacheEntry:
    envelope: dict
    fetched_at: float
    last_good: dict | None


_POLL_CACHE: dict[int, _CacheEntry] = {}


def _vm_unreachable_envelope(last_good: dict | None) -> dict:
    """The instance is stopped: never SSH (never wakes EC2). Reuses the last
    known provider set so the card doesn't blank, marked unavailable."""
    providers = [
        {**p, "availability": "unavailable", "freshness": "unavailable", "error": _ERROR_VM_UNREACHABLE}
        for p in (last_good or {}).get("providers", [])
    ]
    return {"providers": providers, "errors": [{"origin": "vm", "error": _ERROR_VM_UNREACHABLE}]}


def _stale_envelope(last_good: dict, error_code: str) -> dict:
    """A transient SSH/CLI failure: serve the last-good snapshot (with its
    percentages) as stale rather than blanking the card. Only rows that were
    actually `available` degrade to `stale` — a non-available row (e.g.
    `reauth_required`) already carries the freshness `_freshness` requires
    (`unavailable`) and its own actionable error code, and must be left
    untouched so a dead grant keeps rendering as a "reauth required" card
    instead of losing that state to a transport blip."""
    providers = [
        {**p, "freshness": "stale", "error": error_code} if p.get("availability") == "available" else p
        for p in last_good.get("providers", [])
    ]
    return {"providers": providers, "errors": [{"origin": "vm", "error": error_code}]}


async def get_limit_status(user_id: int, ttl_seconds: int | None = None, refresh: bool = False) -> dict:
    """The user's live subscription limit-window status, read via `y usage
    limits --json` over SSH on the user's VM. `refresh=True` is an explicit
    user-initiated retry: it bypasses the poll-cost memo and asks the CLI to
    bypass its own cache too, rather than returning a stale/failed snapshot
    for up to POLL_TTL_SECONDS after the user asked to try again."""
    now = time.monotonic()
    cached = _POLL_CACHE.get(user_id)
    if not refresh and cached is not None and now - cached.fetched_at <= POLL_TTL_SECONDS:
        return cached.envelope

    last_good = cached.last_good if cached else None

    try:
        # resolve_vm_config / is_vm_asleep are inside the try too: a
        # throttled or transient describe_instance_status must degrade the
        # same way a failed SSH read does, not 500 a 60s-polled endpoint.
        vm_config = resolve_vm_config(user_id)

        if is_vm_asleep(vm_config):
            envelope = _vm_unreachable_envelope(last_good)
            _POLL_CACHE[user_id] = _CacheEntry(envelope=envelope, fetched_at=now, last_good=last_good)
            return envelope

        output = await _run_usage_limits_cli(vm_config, refresh=refresh)
        raw = json.loads(output.strip())
        envelope = limits.normalize_envelope(raw, ttl_seconds)
    except Exception as e:
        logger.warning("get_limit_status: CLI read failed for user {}: {}", user_id, e)
        error_code = _error_code(e)
        envelope = (
            {"providers": [], "errors": [{"origin": "vm", "error": error_code}]}
            if last_good is None
            else _stale_envelope(last_good, error_code)
        )
        _POLL_CACHE[user_id] = _CacheEntry(envelope=envelope, fetched_at=now, last_good=last_good)
        return envelope

    if not envelope["providers"] and envelope["errors"]:
        # normalize_envelope reported a malformed/degraded read (e.g.
        # bad_payload from a valid-JSON-wrong-shape response) rather than a
        # genuinely empty account list. Treat it exactly like a CLI
        # exception — serve last_good as stale instead of promoting this
        # providers-less envelope to last_good, or a later transient failure
        # would blank a card that still has real percentages one read ago.
        error_code = envelope["errors"][0].get("error") or _ERROR_BAD_PAYLOAD
        degraded = (
            {"providers": [], "errors": envelope["errors"]}
            if last_good is None
            else _stale_envelope(last_good, error_code)
        )
        _POLL_CACHE[user_id] = _CacheEntry(envelope=degraded, fetched_at=now, last_good=last_good)
        return degraded

    _POLL_CACHE[user_id] = _CacheEntry(envelope=envelope, fetched_at=now, last_good=envelope)
    return envelope
