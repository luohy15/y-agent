"""`claude_tui_usage` reader (todo 2872 sub-task 3): wraps
`agent.claude_usage`'s local (no-SSH) `/usage` scrape behind the shared
envelope contract, plus the ~240s on-VM scrape cache (`_cache.py`).

Uses the *local* execution variants (`read_claude_usage_local`,
`read_claude_login_status_local`), not the SSH ones: `y usage limits`
always runs ON the subscription box, so SSHing back into itself would be a
pointless loopback (see `agent.claude_usage` module docstring).
"""

from __future__ import annotations

import time

from agent.claude_usage import (
    extra_window_key,
    read_claude_login_status_local,
    read_claude_usage_local,
    reset_at_iso,
)
from loguru import logger

from . import _cache
from ._credentials import now_iso

BACKEND = "claude_code"
PROVIDER = "anthropic"
SOURCE = "claude_tui_usage"

ERROR_REAUTH_REQUIRED = "reauth_required"
ERROR_PARSE_FAILED = "parse_failed"


def _window(percent: int | None, reset: str | None) -> dict | None:
    if percent is None:
        return None
    return {"used_percent": float(percent), "reset_at": reset_at_iso(reset)}


def _row(*, availability: str, error: str | None, windows: dict, extra_windows: dict, observed_at: str) -> dict:
    return {
        "backend": BACKEND,
        "provider": PROVIDER,
        "account_id": None,
        "account_name": None,
        "observed_at": observed_at,
        "source": SOURCE,
        "availability": availability,
        "error": error,
        "windows": windows,
        "extra_windows": extra_windows,
    }


async def _scrape_row() -> dict:
    # Cheap check first: skip the several-seconds-long TUI spawn entirely
    # when we already know for certain the box is logged out.
    logged_in = await read_claude_login_status_local()
    if logged_in is False:
        return _row(
            availability=ERROR_REAUTH_REQUIRED, error=ERROR_REAUTH_REQUIRED,
            windows={}, extra_windows={}, observed_at=now_iso(),
        )

    result = await read_claude_usage_local()
    observed_at = now_iso()

    if not result.get("parse_ok"):
        # `ready` (whether the TUI ever reached its idle footer) is what
        # distinguishes a genuinely logged-out box from a launch that
        # succeeded but whose overlay text this parser no longer recognizes
        # (a Claude Code release renaming the window labels). Raw pane text
        # is never put in the envelope -- `read_claude_usage_local` already
        # logs it on a parse failure.
        if result.get("ready"):
            return _row(
                availability="unavailable", error=ERROR_PARSE_FAILED,
                windows={}, extra_windows={}, observed_at=observed_at,
            )
        return _row(
            availability=ERROR_REAUTH_REQUIRED, error=ERROR_REAUTH_REQUIRED,
            windows={}, extra_windows={}, observed_at=observed_at,
        )

    windows = {
        "five_hour": _window(result["session"]["percent"], result["session"]["reset"]),
        "one_week": _window(result["week_all"]["percent"], result["week_all"]["reset"]),
    }
    extra_windows = {}
    extra = result.get("week_extra")
    if extra:
        extra_windows[extra_window_key(extra["label"])] = _window(extra["percent"], extra["reset"])

    return _row(
        availability="available", error=None,
        windows=windows, extra_windows=extra_windows, observed_at=observed_at,
    )


async def read_claude_provider(*, refresh: bool = False) -> dict:
    """The `claude_tui_usage` reader's entry point: read-through the ~240s
    on-VM scrape cache unless `refresh` (an explicit `--refresh`) bypasses
    it. A cache hit keeps the ORIGINAL scrape's `observed_at` -- never
    restamped -- so freshness stays honest."""
    now_ts = time.time()
    if not refresh:
        cached = _cache.read(now_ts)
        if cached is not None:
            return cached

    try:
        item = await _scrape_row()
    except Exception as e:
        logger.warning("claude_tui_usage: scrape failed: {}", e)
        return _row(
            availability="unavailable", error="transport_error",
            windows={}, extra_windows={}, observed_at=now_iso(),
        )

    _cache.write(item, now_ts)
    return item
