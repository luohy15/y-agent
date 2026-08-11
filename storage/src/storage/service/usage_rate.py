"""Realtime CRS run-rate: read from a VM-side cron write, never from the request.

`y usage rate --store` runs once a minute on the user's VM (see
`scripts/usage-rate-store.sh`) and upserts `{envelope, last_error,
last_attempt_at}` into `user_preference` under `USAGE_RATE_KEY`.
`GET /api/usage/rate` reads that one row here instead of SSH-execing the CLI
per request. A stopped VM simply stops writing, so the stored envelope ages
past `STALE_AFTER_SECONDS` (3x the write period) and is served `stale: true`
rather than blanked, which is what the existing web badge already renders.
See docs/prd/bot-usage.md "Realtime run rate" (todo 3121) for the rationale.

The stored JSON is an API boundary like any other: `get_reading` validates it
before returning, exactly as the retired SSH path validated its own transport
payload, so a corrupted or hand-edited row degrades to the closed
`bad_payload` code instead of a 500 or an arbitrary passed-through string.
"""

import math
from datetime import datetime, timezone

from loguru import logger

from storage.service import user_preference as user_pref_service

USAGE_RATE_KEY = "usage_rate_latest"
STALE_AFTER_SECONDS = 180  # 3x the once-a-minute VM cron write period

_STORED_KEYS = {"envelope", "last_error", "last_attempt_at"}
_ENVELOPE_KEYS = {"rpm", "tpm", "window_minutes", "is_historical", "observed_at", "error"}
_KNOWN_ERROR_CODES = {"not_configured", "transport_error", "parse_failed"}
_ERROR_VM_UNREACHABLE = "vm_unreachable"
_ERROR_BAD_PAYLOAD = "bad_payload"


def _unavailable(error: str) -> dict:
    return {
        "rpm": None,
        "tpm": None,
        "window_minutes": None,
        "is_historical": None,
        "observed_at": None,
        "error": error,
    }


def _seconds_since(observed_at: str) -> float:
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if observed.utcoffset() is None:
        # A syntactically valid but timezone-naive ISO string (no offset, no
        # trailing Z) can't be subtracted from an aware `now()`; treat it the
        # same as any other malformed observed_at rather than raising TypeError.
        raise ValueError("observed_at is not timezone-aware")
    return (datetime.now(timezone.utc) - observed).total_seconds()


def _valid_envelope(envelope) -> bool:
    """A *stored* envelope is only ever written on a successful read (see
    `store_reading`), so `error` must be None here; an error code only ever
    lives in the sibling `last_error` field."""
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS or envelope["error"] is not None:
        return False
    return (
        not isinstance(envelope["rpm"], bool) and isinstance(envelope["rpm"], (int, float)) and math.isfinite(envelope["rpm"])
        and not isinstance(envelope["tpm"], bool) and isinstance(envelope["tpm"], (int, float)) and math.isfinite(envelope["tpm"])
        and not isinstance(envelope["window_minutes"], bool) and isinstance(envelope["window_minutes"], (int, float))
        and math.isfinite(envelope["window_minutes"]) and envelope["window_minutes"] >= 0
        and isinstance(envelope["is_historical"], bool)
        and not (envelope["window_minutes"] == 0 and not envelope["is_historical"])
        and isinstance(envelope["observed_at"], str)
    )


def _valid_last_error(last_error) -> bool:
    return last_error is None or (isinstance(last_error, str) and last_error in _KNOWN_ERROR_CODES)


def store_reading(user_id: int, envelope: dict) -> None:
    """Persist one `y usage rate` read attempt. A successful envelope
    (`error is None`) becomes the new stored envelope; a failed attempt keeps
    whatever envelope was already stored and only advances
    `last_error`/`last_attempt_at`, so a transient CRS/CLI hiccup never wipes
    the last good reading."""
    if set(envelope) != _ENVELOPE_KEYS:
        raise ValueError("unexpected rate envelope")

    prior = user_pref_service.get_preference(user_id, USAGE_RATE_KEY)
    prior_value = prior.value if prior and isinstance(prior.value, dict) else None
    prior_envelope = prior_value.get("envelope") if prior_value else None

    stored_envelope = envelope if envelope["error"] is None else prior_envelope
    user_pref_service.upsert_preference(user_id, USAGE_RATE_KEY, {
        "envelope": stored_envelope,
        "last_error": envelope["error"],
        "last_attempt_at": envelope["observed_at"],
    })


def get_reading(user_id: int) -> dict:
    """Return the run-rate envelope for the API. `vm_unreachable` when nothing
    has ever been stored; `bad_payload` when the stored row is not the shape
    `store_reading` writes (never a raise, never an unvalidated pass-through);
    otherwise the last good envelope, marked `stale: true` when the most
    recent write attempt failed or the envelope has aged past
    `STALE_AFTER_SECONDS`."""
    pref = user_pref_service.get_preference(user_id, USAGE_RATE_KEY)
    if pref is None or pref.value is None:
        return _unavailable(_ERROR_VM_UNREACHABLE)

    stored = pref.value
    if not isinstance(stored, dict) or set(stored) != _STORED_KEYS:
        logger.warning("usage_rate.get_reading: malformed stored shape for user {}", user_id)
        return _unavailable(_ERROR_BAD_PAYLOAD)

    envelope = stored["envelope"]
    last_error = stored["last_error"]
    if envelope is not None and not _valid_envelope(envelope):
        logger.warning("usage_rate.get_reading: malformed stored envelope for user {}", user_id)
        return _unavailable(_ERROR_BAD_PAYLOAD)
    if not _valid_last_error(last_error):
        logger.warning("usage_rate.get_reading: unknown stored last_error for user {}", user_id)
        return _unavailable(_ERROR_BAD_PAYLOAD)

    if envelope is None:
        return _unavailable(last_error or _ERROR_VM_UNREACHABLE)
    if last_error is not None:
        return {**envelope, "error": last_error, "stale": True}
    try:
        aged = _seconds_since(envelope["observed_at"]) > STALE_AFTER_SECONDS
    except ValueError:
        logger.warning("usage_rate.get_reading: malformed observed_at for user {}", user_id)
        return _unavailable(_ERROR_BAD_PAYLOAD)
    if aged:
        return {**envelope, "stale": True}
    return envelope
