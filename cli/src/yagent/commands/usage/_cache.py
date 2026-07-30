"""On-VM cache for the Anthropic scrape-backed reader (todo 2872 sub-task 3).

Only the `claude_tui_usage` reader is cached: it spawns a tmux TUI and takes
seconds, while the two HTTP readers (`codex_usage_api`, `xai_billing_credits`)
are cheap and always run fresh. A ~240s TTL caps TUI spawns to roughly one
per 240s regardless of how often the panel polls, and sits comfortably under
the 300s freshness TTL in `storage.service.model_usage_limits`, so a fresh
enough cached read never shows up as `stale`.

Cache hits keep the ORIGINAL scrape's `observed_at` untouched -- restamping
it on a cache hit would make the downstream freshness computation lie about
how old the reading actually is. One file, 0600, atomic replace (same
pattern as `_credentials.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ._credentials import agent_home

TTL_SECONDS = 240


def cache_path() -> Path:
    return agent_home() / ".cache" / "claude-usage.json"


def read(now_ts: float) -> dict | None:
    """Return the cached provider row if it is still within TTL, else None.
    Any read/parse trouble is treated as a cache miss, never an error."""
    path = cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cached_at = data.get("cached_at")
    if not isinstance(cached_at, (int, float)) or now_ts - cached_at > TTL_SECONDS:
        return None
    item = data.get("item")
    return item if isinstance(item, dict) else None


def write(item: dict, now_ts: float) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".claude-usage-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"cached_at": now_ts, "item": item}, f)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
