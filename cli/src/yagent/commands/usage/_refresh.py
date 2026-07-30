"""Ensure a fresh access token for a provider (todo 2872 read-through
redesign): read the vendor CLI's own credential file as the single source of
truth, refresh via `_oauth` when the access token is expired, and write the
rotated grant straight back into that same vendor file -- never into a
y-agent-owned copy. `y usage login <provider>` no longer exists: there is
nothing left to import, because there is no second grant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import _credentials as vendor
from . import _oauth
from ._errors import CredentialsMissingError, ReauthRequiredError

# 60s expiry margin: refresh proactively rather than racing a read against
# the token dying mid-request.
_EXPIRY_MARGIN_SECONDS = 60


def _is_valid(grant: dict) -> bool:
    token = grant.get("access_token")
    expires_at = grant.get("expires_at")
    if not token or not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < exp - timedelta(seconds=_EXPIRY_MARGIN_SECONDS)


def ensure_access_token(provider: str, *, path: Path | None = None) -> str:
    """Return a usable access token for `provider`, read straight from the
    vendor CLI's own credential file, refreshing (and writing the rotated
    grant back into that same file) if the stored one is missing or
    expiring within the margin.

    Raises `CredentialsMissingError` if the vendor file doesn't exist or
    holds no refresh_token (not logged in), or `ReauthRequiredError` if the
    provider rejected the refresh_token (`invalid_grant`) -- in that case
    the vendor file is left completely untouched.
    """
    path = path or vendor.vendor_auth_path(provider)
    grant = vendor.read_grant(provider, path)
    if grant is None:
        raise CredentialsMissingError(provider)
    if _is_valid(grant):
        return grant["access_token"]

    outcome: dict = {}

    def _refresh_under_lock(data: dict):
        # Re-read under the lock: another process may have already
        # refreshed this provider while we waited to acquire it.
        current = vendor.extract_grant(provider, data)
        if current is None:
            return None  # not logged in; nothing to refresh or write
        if _is_valid(current):
            outcome["access_token"] = current["access_token"]
            return None  # no-op: nothing to write, the file is already fresh

        refresh_fn = _oauth.REFRESH_FUNCS[provider]
        result = refresh_fn(current["refresh_token"])
        if not result.get("ok"):
            # Never write on failure -- the vendor file must stay
            # byte-identical so a dead grant never masquerades as a partial
            # rotation.
            outcome["error"] = result.get("error")
            return None

        outcome["access_token"] = result["access_token"]
        return vendor.apply_refresh(provider, data, result)

    vendor.mutate_vendor_file(path, _refresh_under_lock)

    if "access_token" not in outcome:
        # Either `_refresh_under_lock` flagged it explicitly, or the vendor
        # file vanished between our unlocked read above and the lock being
        # acquired (so `fn` was never even called) -- both are "not logged
        # in" from here.
        if outcome.get("error"):
            raise ReauthRequiredError(provider)
        raise CredentialsMissingError(provider)
    return outcome["access_token"]
