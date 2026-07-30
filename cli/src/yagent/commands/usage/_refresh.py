"""Ensure a fresh access token for a provider (sub-task 2): refresh via
`_oauth`, mandatory write-back of the (possibly rotated) grant through
`_credentials`, `invalid_grant` -> `status=reauth_required` instead of a
raised transport error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import _credentials as store
from . import _oauth
from ._errors import CredentialsMissingError, ReauthRequiredError

# 60s expiry margin: refresh proactively rather than racing a read against
# the token dying mid-request.
_EXPIRY_MARGIN_SECONDS = 60


def _is_valid(record: dict) -> bool:
    token = record.get("access_token")
    expires_at = record.get("expires_at")
    if not token or not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < exp - timedelta(seconds=_EXPIRY_MARGIN_SECONDS)


def ensure_access_token(provider: str) -> str:
    """Return a usable access token for `provider`, refreshing (and
    persisting the rotated grant) if the stored one is missing or expiring
    within the margin.

    Raises `CredentialsMissingError` if no grant is stored yet, or
    `ReauthRequiredError` if the stored refresh_token is/was rejected
    (`invalid_grant`) -- a prior `reauth_required` status short-circuits
    before a doomed network round trip.
    """
    record = store.get_record(provider)
    if not record or not record.get("refresh_token"):
        raise CredentialsMissingError(provider)
    if record.get("status") == "reauth_required":
        raise ReauthRequiredError(provider)
    if _is_valid(record):
        return record["access_token"]

    refresh_fn = _oauth.REFRESH_FUNCS[provider]
    result = refresh_fn(record["refresh_token"])
    if not result.get("ok"):
        store.update_record(
            provider,
            status="reauth_required",
            last_error=result.get("error"),
            last_refresh_at=store.now_iso(),
        )
        raise ReauthRequiredError(provider)

    updates = {
        "access_token": result["access_token"],
        # Mandatory write-back: prefer the rotated token; fall back to the
        # existing one only if this response omitted it, so a single
        # malformed response can't strand the grant unrefreshable.
        "refresh_token": result.get("refresh_token") or record["refresh_token"],
        "expires_at": result["expires_at"],
        "status": "active",
        "last_refresh_at": store.now_iso(),
        "last_error": None,
    }
    if result.get("scopes"):
        updates["scopes"] = result["scopes"]
    if result.get("extra"):
        updates["extra"] = {**(record.get("extra") or {}), **result["extra"]}
    store.update_record(provider, **updates)
    return updates["access_token"]
