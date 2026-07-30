"""Read-through access to each vendor CLI's own OAuth credential file
(todo 2872 read-through redesign).

y-agent no longer keeps a copy of any provider grant. `~/.codex/auth.json`
and `~/.grok/auth.json` are the single source of truth; this module reads
them live and, on refresh, writes the rotated grant straight back into that
same file -- exactly what the vendor CLI would have done itself. That is
what a live collision check (todo 2872) proved necessary: OpenAI revokes a
prior session account-wide on every fresh `codex login`, so a
separately-held y-agent copy dies on the next login and never recovers.
Reading through removes the second grant entirely, so there is nothing left
for a vendor login to invalidate.

Scope: **openai and xai only** (`PROVIDERS`). Anthropic reads live usage via
the `/usage` TUI scrape (`agent.claude_usage`), where the `claude` CLI owns
its own subscription credential end to end -- no grant, no refresh path, no
file, here or anywhere in y-agent.

Vendor file shapes (both live-verified, todo 2872):
    - `~/.codex/auth.json`: `{"tokens": {"access_token", "refresh_token",
      "id_token", "account_id"}, "last_refresh", ...}`. No `expires_at`
      field -- the access token's own JWT `exp` claim is the expiry.
    - `~/.grok/auth.json`: the credential record is nested under a dynamic
      `"{oidc_issuer}::{oidc_client_id}"` key, not at the top level. Fields
      of interest: `key` (the access token), `refresh_token`, `expires_at`
      (a plain ISO8601 string).

Write safety is the core guarantee this module provides, not an
afterthought: atomic replace (temp file in the same directory, fsync,
`os.replace`) under an exclusive advisory lock (`fcntl.flock` on a sibling
`.lock` file) so (a) a concurrently running vendor CLI never observes a
truncated or half-written file and (b) two y-agent readers refreshing the
same provider at once can't lose one's rotated refresh_token to the other's
stale write -- the second one re-reads under the lock and finds the first
one's refresh already fresh, rather than racing a doomed second refresh
call. The original file's mode and ownership are preserved on every write.
On refresh failure the vendor file is left completely untouched: `_refresh.py`
never calls back into the writer unless the provider round trip already
succeeded.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import _oauth

PROVIDERS = ("openai", "xai")


def agent_home() -> Path:
    return Path(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")))


def codex_auth_path() -> Path:
    return Path(os.path.expanduser("~/.codex")) / "auth.json"


def grok_auth_path() -> Path:
    return Path(os.path.expanduser("~/.grok")) / "auth.json"


def vendor_auth_path(provider: str) -> Path:
    if provider == "openai":
        return codex_auth_path()
    if provider == "xai":
        return grok_auth_path()
    raise ValueError(f"unsupported provider {provider!r}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


class _FileLock:
    """Advisory exclusive lock, colocated next to the vendor file (never the
    file itself), guarding the read-refresh-write-back sequence."""

    def __init__(self, path: Path):
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        self._fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        assert self._fd is not None
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None


def load_vendor_file(path: Path) -> dict | None:
    """Parse the vendor's JSON file. Missing, unreadable, empty or invalid
    JSON all normalize to `None` (not logged in) -- never a crash."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def save_vendor_file(path: Path, data: dict) -> None:
    """Atomically replace `path` with `data`, preserving its exact original
    mode (0600 if the file did not exist yet, which cannot happen in
    practice here since a write only ever follows a successful read of the
    same file). Temp file lives in the same directory so `os.replace` is a
    same-filesystem atomic rename."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def mutate_vendor_file(path: Path, fn: Callable[[dict], dict | None]) -> dict | None:
    """Run `fn(data) -> data | None` under the exclusive lock on `path`.
    `fn` mutates and returns the same top-level structure `load_vendor_file`
    produced (so every field it doesn't touch survives untouched, including
    Grok's dynamic issuer/client_id nesting); returning `None` means "do not
    write" -- used both when a concurrent refresh already made this one a
    no-op and when the refresh call itself failed. Returns `None` if the
    file vanished/emptied between the caller's own check and the lock being
    acquired."""
    lock = _FileLock(_lock_path(path))
    with lock:
        data = load_vendor_file(path)
        if data is None:
            return None
        new_data = fn(data)
        if new_data is not None:
            save_vendor_file(path, new_data)
        return new_data


# --- OpenAI / Codex ---------------------------------------------------------


def _openai_extra(tokens: dict) -> dict | None:
    extra: dict = {}
    id_token = tokens.get("id_token")
    if id_token:
        claims = _oauth._decode_jwt_payload(id_token) or {}
        auth_claim = claims.get("https://api.openai.com/auth") or {}
        if auth_claim.get("chatgpt_account_id"):
            extra["chatgpt_account_id"] = auth_claim["chatgpt_account_id"]
    if tokens.get("account_id") and "chatgpt_account_id" not in extra:
        extra["chatgpt_account_id"] = tokens["account_id"]
    return extra or None


def _openai_access_token_expiry(access_token: str | None) -> str | None:
    """Codex's own file has no `expires_at` field -- the access token is a
    JWT, and its `exp` claim is the actual expiry."""
    if not access_token:
        return None
    claims = _oauth._decode_jwt_payload(access_token) or {}
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_openai_grant(data: dict) -> dict | None:
    tokens = data.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None
    access_token = tokens.get("access_token")
    return {
        "refresh_token": refresh_token,
        "access_token": access_token,
        "expires_at": _openai_access_token_expiry(access_token),
        "extra": _openai_extra(tokens),
    }


def _apply_openai_refresh(data: dict, result: dict) -> dict:
    tokens = data.setdefault("tokens", {})
    tokens["access_token"] = result["access_token"]
    if result.get("refresh_token"):
        tokens["refresh_token"] = result["refresh_token"]
    if result.get("id_token"):
        tokens["id_token"] = result["id_token"]
    data["last_refresh"] = now_iso()
    return data


# --- xAI / Grok --------------------------------------------------------------


def _find_grok_record(data: dict) -> dict | None:
    """The real `~/.grok/auth.json` nests the credential record under a
    dynamic `"{oidc_issuer}::{oidc_client_id}"` key rather than at the top
    level. Support both: a flat top-level record (defensive / for fixtures)
    and the real nested shape (first value that looks like a credential
    record). Returns a reference into `data`, so mutating fields on the
    returned dict mutates `data` in place and preserves whatever key it was
    nested under."""
    if not isinstance(data, dict):
        return None
    if data.get("refresh_token"):
        return data
    for value in data.values():
        if isinstance(value, dict) and value.get("refresh_token"):
            return value
    return None


def _extract_xai_grant(data: dict) -> dict | None:
    record = _find_grok_record(data)
    if record is None:
        return None
    return {
        "refresh_token": record["refresh_token"],
        "access_token": record.get("key"),
        "expires_at": record.get("expires_at"),
        "extra": None,
    }


def _apply_xai_refresh(data: dict, result: dict) -> dict:
    record = _find_grok_record(data)
    if record is None:
        # The record existed moments ago (extract_grant found it under the
        # same lock) -- vanishing here would mean the file was rewritten by
        # something else entirely. Refuse to guess where to put it.
        raise LookupError("grok credential record not found during write-back")
    record["key"] = result["access_token"]
    if result.get("refresh_token"):
        record["refresh_token"] = result["refresh_token"]
    record["expires_at"] = result["expires_at"]
    return data


# --- provider dispatch --------------------------------------------------------

_EXTRACTORS: dict[str, Callable[[dict], dict | None]] = {
    "openai": _extract_openai_grant,
    "xai": _extract_xai_grant,
}

_APPLIERS: dict[str, Callable[[dict, dict], dict]] = {
    "openai": _apply_openai_refresh,
    "xai": _apply_xai_refresh,
}


def extract_grant(provider: str, data: dict) -> dict | None:
    """Pull `{refresh_token, access_token, expires_at, extra}` out of an
    already-loaded vendor file dict, in that provider's own shape."""
    return _EXTRACTORS[provider](data)


def apply_refresh(provider: str, data: dict, result: dict) -> dict:
    """Write a successful `_oauth.refresh_*` result into `data` (an
    already-loaded vendor file dict), in that provider's own shape."""
    return _APPLIERS[provider](data, result)


def read_grant(provider: str, path: Path | None = None) -> dict | None:
    """Unlocked read straight from the vendor file -- fine for a plain
    status read; refreshing must go through `_refresh.ensure_access_token`
    (which takes the lock) instead."""
    path = path or vendor_auth_path(provider)
    data = load_vendor_file(path)
    if data is None:
        return None
    return extract_grant(provider, data)
