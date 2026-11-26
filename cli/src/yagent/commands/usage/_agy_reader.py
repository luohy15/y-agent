"""`agy_usage_cli` reader (todo 4461): the Antigravity CLI's own `/usage`
report, run as a subprocess on the VM.

The vendor CLI is the only thing that reads its login, so y-agent never reads
or rotates the agy OAuth token (unlike the Codex/Grok readers in
`_http_readers.py`, which refresh the vendor credential file themselves).
`agy -p "/usage" --output-format json` is read-only, spends no model tokens,
and returns in a couple of seconds.

Live shape (2026-11-26): `command.data.groups[].buckets[]`, each bucket
carrying `{id, name, window: "weekly"|"5h", remaining_fraction, reset_time}`.
Only the first group ("Gemini Models") is collected; the second ("Claude and
GPT models") is out of scope. A bucket's `reset_time` is the epoch placeholder
`1970-01-01T00:00:00Z` when there is no reset, which must render as null
rather than a 1970 countdown.

Signed out, the CLI prints "Authentication required..." on stderr and then
waits for its own long auth timeout, so a short kill timeout plus the stderr
text is the only fast signal; that maps to `reauth_required`, never a 0%
reading. Parsed defensively: any shape this module doesn't recognize
normalizes to `parse_failed`, never a fabricated percent.
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone

from . import _credentials as store

_TIMEOUT_SECONDS = 15.0
# Never inherit the caller's cwd: agy is run from a neutral directory, and the
# vendor stores its login under HOME, which is inherited unchanged.
_CWD = "/tmp"

SOURCE = "agy_usage_cli"

ERROR_NOT_LOGGED_IN = "not_logged_in"
ERROR_REAUTH_REQUIRED = "reauth_required"
ERROR_PARSE_FAILED = "parse_failed"
ERROR_TRANSPORT = "transport_error"

# The two buckets the Gemini group reports. The UI draws `one_week`, the same
# window it draws for Codex; the 5-hour bucket stays in the payload.
_WINDOW_KINDS = {"weekly": "one_week", "5h": "five_hour"}

# The CLI cannot distinguish an expired from a missing login, and its
# signed-out output differs by version, so match a small set of phrases on
# stderr rather than one exact string.
_AUTH_MARKERS = (
    "authentication required",
    "not logged in",
    "please log in",
    "login required",
)


def _row(*, error, availability, windows, observed_at) -> dict:
    return {
        "backend": "agy",
        "provider": "google",
        "account_id": None,
        "account_name": None,
        "observed_at": observed_at,
        "source": SOURCE,
        "availability": availability,
        "error": error,
        "windows": windows,
        "extra_windows": {},
    }


def read_agy_provider() -> dict:
    """Run `agy -p "/usage" --output-format json` and map its primary group
    to five_hour/one_week windows. Never raises: an auth wall, a timeout, a
    missing binary, or an unrecognized shape becomes an error row."""
    observed_at = store.now_iso()
    try:
        proc = subprocess.run(
            ["agy", "-p", "/usage", "--output-format", "json"],
            cwd=_CWD,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        if _looks_unauthenticated(_as_text(exc.stderr)):
            return _row(error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                        windows={}, observed_at=observed_at)
        return _row(error=ERROR_TRANSPORT, availability="unavailable",
                    windows={}, observed_at=observed_at)
    except (OSError, subprocess.SubprocessError, ValueError):
        # Includes FileNotFoundError (agy not installed on this node) and a
        # bad argv. Both are transport-level, never a provider verdict.
        return _row(error=ERROR_TRANSPORT, availability="unavailable",
                    windows={}, observed_at=observed_at)

    stderr = proc.stderr or ""
    if proc.returncode != 0:
        if _looks_unauthenticated(stderr):
            return _row(error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                        windows={}, observed_at=observed_at)
        if proc.returncode == 2:
            # The CLI's documented Gemini API-key shape (exit 2, stderr, no
            # stdout), not reproducible on the authenticated VM. It means the
            # CLI found no usable login, so it maps to not_logged_in.
            return _row(error=ERROR_NOT_LOGGED_IN, availability="unavailable",
                        windows={}, observed_at=observed_at)
        return _row(error=ERROR_TRANSPORT, availability="unavailable",
                    windows={}, observed_at=observed_at)

    try:
        body = json.loads(proc.stdout)
    except (TypeError, ValueError):
        return _row(error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, observed_at=observed_at)

    windows = _parse_windows(body)
    if not windows:
        return _row(error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, observed_at=observed_at)

    return _row(error=None, availability="available", windows=windows,
                observed_at=observed_at)


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _looks_unauthenticated(stderr: str) -> bool:
    text = _as_text(stderr).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _parse_windows(body) -> dict:
    """The first group's buckets, keyed by window kind. An unrecognized or
    percent-less bucket is skipped rather than invented; no usable bucket
    yields `{}`, which the caller maps to `parse_failed`."""
    if not isinstance(body, dict):
        return {}
    command = body.get("command")
    data = command.get("data") if isinstance(command, dict) else None
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list) or not groups or not isinstance(groups[0], dict):
        return {}
    buckets = groups[0].get("buckets")
    if not isinstance(buckets, list):
        return {}

    windows: dict = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        kind = _WINDOW_KINDS.get(bucket.get("window"))
        if not kind or kind in windows:
            continue
        percent = _used_percent(bucket.get("remaining_fraction"))
        if percent is None:
            continue
        windows[kind] = {"used_percent": percent, "reset_at": _reset_iso(bucket.get("reset_time"))}
    return windows


def _used_percent(remaining_fraction) -> float | None:
    """`(1 - remaining_fraction) * 100`, finite and clamped to [0, 100]; None
    for anything malformed (missing, bool, non-numeric, NaN, infinity) so a
    missing reading can never masquerade as 0% used."""
    if isinstance(remaining_fraction, bool) or not isinstance(remaining_fraction, (int, float)):
        return None
    if not math.isfinite(remaining_fraction):
        return None
    return max(0.0, min(100.0, (1.0 - remaining_fraction) * 100.0))


def _reset_iso(value) -> str | None:
    """The bucket's ISO reset time, or None for an absent/unparseable value
    or the epoch placeholder (`1970-01-01T00:00:00Z`), which means "no
    reset"."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.timestamp() <= 0:
        return None
    return value
