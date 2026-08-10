"""Read CRS's live RPM/TPM dashboard metrics through the user's VM CLI.

Like usage_limits, this keeps CRS credentials and provider traffic off Lambda,
never wakes a stopped VM, memoizes automatic panel polls, and returns only
closed error codes to callers.
"""

import json
import math
import os
import time
from dataclasses import dataclass

from loguru import logger

from agent.config import resolve_vm_config
from agent.ec2_wake import is_vm_asleep
from agent.tool_base import Tool

POLL_TTL_SECONDS = int(os.getenv("USAGE_RATE_POLL_TTL_SECONDS", "60"))
_CLI_TIMEOUT_SECONDS = 30.0
_ERROR_VM_UNREACHABLE = "vm_unreachable"
_ERROR_CLI_FAILED = "cli_failed"
_ERROR_BAD_PAYLOAD = "bad_payload"


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def _run_usage_rate_cli(vm_config) -> str:
    runner = _CmdRunner(vm_config)
    return await runner.run_cmd(["y", "usage", "rate", "--json"], timeout=_CLI_TIMEOUT_SECONDS)


def _unavailable(error: str) -> dict:
    return {
        "rpm": None,
        "tpm": None,
        "window_minutes": None,
        "is_historical": None,
        "observed_at": None,
        "error": error,
    }


def _validate(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"rpm", "tpm", "window_minutes", "is_historical", "observed_at", "error"}:
        raise ValueError("unexpected rate envelope")
    if raw["error"] is not None:
        if raw["error"] not in {"not_configured", "transport_error", "parse_failed"}:
            raise ValueError("unknown rate error")
        if any(raw[key] is not None for key in ("rpm", "tpm", "window_minutes", "is_historical")) or not isinstance(raw["observed_at"], str):
            raise ValueError("malformed failed rate envelope")
        return raw
    if (
        isinstance(raw["rpm"], bool) or not isinstance(raw["rpm"], (int, float)) or not math.isfinite(raw["rpm"])
        or isinstance(raw["tpm"], bool) or not isinstance(raw["tpm"], (int, float)) or not math.isfinite(raw["tpm"])
        or isinstance(raw["window_minutes"], bool) or not isinstance(raw["window_minutes"], (int, float))
        or not math.isfinite(raw["window_minutes"]) or raw["window_minutes"] < 0
        or not isinstance(raw["is_historical"], bool)
        or (raw["window_minutes"] == 0 and not raw["is_historical"])
        or not isinstance(raw["observed_at"], str)
    ):
        raise ValueError("malformed rate envelope")
    return raw


@dataclass
class _CacheEntry:
    envelope: dict
    fetched_at: float
    last_good: dict | None


_POLL_CACHE: dict[int, _CacheEntry] = {}


def _stale(last_good: dict, error: str) -> dict:
    return {**last_good, "error": error, "stale": True}


async def get_usage_rate(user_id: int) -> dict:
    """Return the current CRS dashboard rate without waking the user's VM."""
    now = time.monotonic()
    cached = _POLL_CACHE.get(user_id)
    if cached is not None and now - cached.fetched_at <= POLL_TTL_SECONDS:
        return cached.envelope

    last_good = cached.last_good if cached else None
    try:
        vm_config = resolve_vm_config(user_id)
        if is_vm_asleep(vm_config):
            envelope = _unavailable(_ERROR_VM_UNREACHABLE)
        else:
            envelope = _validate(json.loads((await _run_usage_rate_cli(vm_config)).strip()))
    except json.JSONDecodeError:
        logger.warning("get_usage_rate: invalid JSON from VM for user {}", user_id)
        envelope = _unavailable(_ERROR_BAD_PAYLOAD)
    except ValueError:
        logger.warning("get_usage_rate: invalid envelope from VM for user {}", user_id)
        envelope = _unavailable(_ERROR_BAD_PAYLOAD)
    except Exception as e:
        logger.warning("get_usage_rate: CLI read failed for user {}: {}", user_id, e)
        envelope = _unavailable(_ERROR_CLI_FAILED)

    if envelope["error"] in {_ERROR_CLI_FAILED, _ERROR_BAD_PAYLOAD} and last_good is not None:
        envelope = _stale(last_good, envelope["error"])
    last_good = envelope if envelope["error"] is None else last_good
    _POLL_CACHE[user_id] = _CacheEntry(envelope=envelope, fetched_at=now, last_good=last_good)
    return envelope
