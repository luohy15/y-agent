"""Per-provider OAuth request shapes for the direct provider-usage credential
layer (plan-2872-direct-provider-usage.md, sub-tasks 1-2).

Scope note: Anthropic has **no** y-agent-owned grant or refresh path here.
Per the plan's per-provider verdict, Anthropic reads live usage via the
revived `/usage` TUI scrape (`agent.claude_usage`), where the `claude` CLI
owns and refreshes its own subscription credential -- no PKCE flow, no
refresh module, no grant storage. This module covers OpenAI and xAI only.

Endpoints, client_ids, body encodings below are exactly as
reverse-engineered from claude-relay-service and documented in the plan for
the refresh grant -- that is the piece unit-tested against mocked httpx here.

Each `refresh_*` function returns a plain result dict rather than raising on
`invalid_grant`, so a dead grant can flip to `reauth_required` instead of
crashing a live/limits read:
    {"ok": True, "access_token", "refresh_token", "expires_at", "scopes"?, "extra"?, "id_token"?}
    {"ok": False, "reauth_required": True, "error": "invalid_grant"}
Transport/HTTP errors that are *not* invalid_grant still raise -- those are
transient and must not be mistaken for a dead grant.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx

_TIMEOUT_SECONDS = 15.0

# --- OpenAI / Codex --------------------------------------------------------

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_SCOPE = "openid profile email"
_OPENAI_DEFAULT_EXPIRES_IN = 3600


def refresh_openai(refresh_token: str) -> dict:
    resp = httpx.post(
        OPENAI_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": OPENAI_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": OPENAI_SCOPE,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_TIMEOUT_SECONDS,
    )
    invalid = _invalid_grant(resp)
    if invalid:
        return invalid
    resp.raise_for_status()
    body = resp.json()
    extra = _openai_extra_from_id_token(body.get("id_token"))
    return {
        "ok": True,
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
        # Codex's own auth.json stores the id_token verbatim (it is where
        # chatgpt_account_id lives on read-through); pass it along so the
        # write-back can keep it current too.
        "id_token": body.get("id_token"),
        "expires_at": _expires_at_from(body, _OPENAI_DEFAULT_EXPIRES_IN),
        "scopes": OPENAI_SCOPE.split(),
        "extra": extra,
    }


def _openai_extra_from_id_token(id_token: str | None) -> dict | None:
    """`chatgpt_account_id` / user / org info live inside the id_token's
    `https://api.openai.com/auth` claim (plan: openaiAccountService.js)."""
    if not id_token:
        return None
    claims = _decode_jwt_payload(id_token)
    if not claims:
        return None
    auth_claim = claims.get("https://api.openai.com/auth") or {}
    extra = {}
    if auth_claim.get("chatgpt_account_id"):
        extra["chatgpt_account_id"] = auth_claim["chatgpt_account_id"]
    user_id = auth_claim.get("chatgpt_user_id") or auth_claim.get("user_id")
    if user_id:
        extra["chatgpt_user_id"] = user_id
    if auth_claim.get("organization_id"):
        extra["organization_id"] = auth_claim["organization_id"]
    return extra or None


# --- xAI / Grok -------------------------------------------------------------

XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"
# Vendor default when a refresh response omits expires_in (~6h access token).
_XAI_DEFAULT_EXPIRES_IN = 21600


def refresh_xai(refresh_token: str) -> dict:
    resp = httpx.post(
        XAI_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": XAI_CLIENT_ID,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_TIMEOUT_SECONDS,
    )
    invalid = _invalid_grant(resp)
    if invalid:
        return invalid
    resp.raise_for_status()
    body = resp.json()
    return {
        "ok": True,
        # xAI rotates refresh_token on every refresh; a missing one here
        # would be a vendor contract break, not something to paper over.
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
        "expires_at": _expires_at_from(body, _XAI_DEFAULT_EXPIRES_IN),
    }


# --- shared helpers ----------------------------------------------------------

REFRESH_FUNCS = {
    "openai": refresh_openai,
    "xai": refresh_xai,
}


# Dead-grant indicators seen in the `error` field across providers. xAI uses
# the flat RFC 6749 shape (`{"error": "invalid_grant"}`, confirmed live).
# OpenAI does NOT: a live probe (todo 2872) against a refresh_token that a
# fresh `codex login` had just superseded returned 401 with a NESTED shape,
# `{"error": {"code": "refresh_token_invalidated", "message": "Your session
# has ended. Please log in again.", "type": "invalid_request_error"}}` --
# `body.get("error") == "invalid_grant"` never matches that, so without this
# the exact reauth_required-without-raising behavior sub-task 2 promises
# would raise a bare HTTPStatusError on real OpenAI traffic instead.
_DEAD_GRANT_CODES = {"invalid_grant", "refresh_token_invalidated", "refresh_token_expired"}


def _invalid_grant(resp: httpx.Response) -> dict | None:
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        error = body.get("error")
        code = error if isinstance(error, str) else (error or {}).get("code")
        if code in _DEAD_GRANT_CODES:
            return {"ok": False, "reauth_required": True, "error": "invalid_grant"}
    return None


def _expires_at_from(body: dict, default_seconds: int) -> str:
    if body.get("expires_at"):
        return body["expires_at"]
    seconds = body.get("expires_in")
    if seconds is None:
        seconds = default_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _decode_jwt_payload(token: str) -> dict | None:
    """Decode a JWT's payload segment without verifying the signature --
    the token was issued to us by the provider we're about to call, so we
    only need the claims, not proof of authenticity."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None
