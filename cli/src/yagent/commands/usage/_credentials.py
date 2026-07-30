"""Credential store for provider-direct subscription usage reads.

One file, `$Y_AGENT_HOME/.credentials/provider-usage.json`, holding one
record per provider. Scope note: this store is for **openai and xai only**
(`PROVIDERS`) -- Anthropic reads live usage via the revived `/usage` TUI
scrape (`agent.claude_usage`), where the `claude` CLI owns its own
subscription credential and y-agent stores nothing. The store's own shape is
otherwise provider-agnostic (a generic locked JSON KV keyed by provider
name), so a provider whose CLI later ships a headless usage command can move
to a shell-out reader without reworking this module.

Deliberately separate from each vendor CLI's own credential file
(`~/.codex/auth.json`, `~/.grok/auth.json`): y-agent holds its own grant per
provider so refreshing it never rotates -- and breaks -- the vendor CLI's
copy of the same grant (plan-2872-direct-provider-usage.md).

Record shape (all fields optional except where noted):
    refresh_token, access_token, expires_at (ISO8601 UTC), scopes (list),
    extra (dict, e.g. chatgpt_account_id), status ("active" |
    "reauth_required"), last_refresh_at, last_error.

No secrets ever leave this file: it is never returned by an API response
and never logged.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PROVIDERS = ("openai", "xai")


def agent_home() -> Path:
    return Path(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")))


def credentials_path() -> Path:
    return agent_home() / ".credentials" / "provider-usage.json"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


class _FileLock:
    """Advisory exclusive lock guarding read-modify-write on the store, so
    two concurrent CLI invocations refreshing the same provider can't lose
    a rotated refresh_token to a lost-update race."""

    def __init__(self, path: Path):
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._path.parent, 0o700)
        self._fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        assert self._fd is not None
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None


def _load_unlocked(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return {}
    return json.loads(content)


def _save_unlocked(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".provider-usage-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_store() -> dict:
    """Unlocked read -- fine for a plain status/list read; refreshers must
    use `mutate` instead so the read-modify-write is atomic."""
    return _load_unlocked(credentials_path())


def get_record(provider: str) -> dict | None:
    return load_store().get(provider)


def mutate(fn: Callable[[dict], dict]) -> dict:
    """Run `fn(store) -> store` under the exclusive file lock, then
    atomically persist the result. Returns the persisted store."""
    path = credentials_path()
    lock = _FileLock(_lock_path(path))
    with lock:
        store = _load_unlocked(path)
        new_store = fn(store)
        _save_unlocked(path, new_store)
        return new_store


def set_record(provider: str, record: dict) -> dict:
    def _update(store: dict) -> dict:
        store = dict(store)
        store[provider] = record
        return store

    return mutate(_update)[provider]


def update_record(provider: str, **fields) -> dict:
    """Read-modify-write a subset of one provider's fields under the lock."""

    def _update(store: dict) -> dict:
        store = dict(store)
        record = dict(store.get(provider) or {})
        record.update(fields)
        store[provider] = record
        return store

    return mutate(_update)[provider]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
