"""Host MCP operations that combine credential custody with network I/O.

The backend host contract (v21 `mcp_*` capabilities) and the runtime gateway
call these; they take the internal owner id and public connector ids, and
return the same sanitized projections as `storage.service.mcp`. Database
transactions never span network I/O: OAuth state is consumed and refresh
slots are claimed in short transactions, the network call runs outside, and
the result is written back only if the identity/claim it belonged to is
still current.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Mapping, Optional

from loguru import logger

from storage.service import mcp as svc
from storage.service.mcp import McpError, validate_https_url
from agent.mcp import oauth
from agent.mcp.client import McpHttpClient
from agent.mcp.egress import Egress, remaining

REFRESH_SKEW_MS = 60 * 1000
REFRESH_WAIT_ATTEMPTS = 3
REFRESH_WAIT_S = 0.5
MAX_CALLBACK_PARAM = 4096
CALLBACK_OUTCOMES = ("connected", "denied", "expired", "invalid", "failed", "superseded")

_default_egress: Optional[Egress] = None


def default_egress() -> Egress:
    global _default_egress
    if _default_egress is None:
        _default_egress = Egress()
    return _default_egress


def redirect_uri() -> str:
    configured = os.environ.get("Y_AGENT_MCP_OAUTH_REDIRECT_URI", "").strip()
    if not configured:
        raise McpError("not_ready", "OAuth callback URL is not configured for this deployment")
    return validate_https_url(configured)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def connect(user_id: int, connector_id: str, *, egress: Optional[Egress] = None) -> dict[str, Any]:
    """Start an authorization; returns the provider URL, never tokens."""
    egress = egress or default_egress()
    callback = redirect_uri()
    material = svc.oauth_client_material(user_id, connector_id)
    meta = oauth.discover(egress, material["endpoint"])
    preset = svc.PRESETS.get(material["preset"] or "") or {}
    scope = oauth.select_scope(meta, tuple(preset.get("scopes", ())))
    client = oauth.choose_client(egress, meta, callback, material["manual_client"], scope)
    verifier, challenge = oauth.pkce_pair()
    state = oauth.new_state()
    tx = svc.begin_oauth_transaction(
        user_id, connector_id, identity_generation=material["identity_generation"], state=state,
        secret={"code_verifier": verifier, "client_secret": client.client_secret},
        issuer=meta.issuer, resource=meta.resource, redirect_uri=callback,
        client_id=client.client_id, token_endpoint=meta.token_endpoint,
        binding_meta={"token_endpoint_auth_method": client.token_endpoint_auth_method,
                      "revocation_endpoint": meta.revocation_endpoint,
                      "iss_parameter_supported": meta.iss_parameter_supported,
                      "scope": scope, "client_registered": client.registered},
    )
    url = oauth.authorization_url(meta, client, redirect_uri=callback, state=state,
                                  challenge=challenge, scope=scope)
    return {"authorization_url": url, "transaction_id": tx["transaction_id"],
            "expires_at_unix": tx["expires_at_unix"]}


def _param(params: Mapping[str, Any], key: str) -> Optional[str]:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_CALLBACK_PARAM:
        return ""
    return value


def handle_callback(params: Mapping[str, Any], *, egress: Optional[Egress] = None) -> dict[str, Any]:
    """Consume the state first (single use even on denial), then validate the
    issuer and exchange the code once. Only a closed outcome and the opaque
    transaction id leave this function."""
    egress = egress or default_egress()
    try:
        tx = svc.consume_oauth_state(_param(params, "state"))
    except McpError as err:
        return {"outcome": "expired" if err.code == "oauth_state_expired" else "invalid",
                "transaction_id": None}

    def fail(status: str, code: str, outcome: str) -> dict[str, Any]:
        svc.fail_oauth_transaction(tx.transaction_id, status=status, error_code=code)
        return {"outcome": outcome, "transaction_id": tx.transaction_id}

    iss = _param(params, "iss")
    if iss is not None and iss != tx.issuer:
        return fail("failed", "auth_failed", "failed")
    if iss is None and tx.binding_meta.get("iss_parameter_supported"):
        return fail("failed", "auth_failed", "failed")
    error = _param(params, "error")
    if error is not None:
        if error == "access_denied":
            return fail("denied", "access_denied", "denied")
        return fail("failed", "auth_failed", "failed")
    code = _param(params, "code")
    if not code:
        return fail("failed", "auth_failed", "failed")
    method = tx.binding_meta.get("token_endpoint_auth_method") or "none"
    client = oauth.OAuthClient(tx.client_id, tx.secret.get("client_secret"), method)
    try:
        token = oauth.exchange_code(egress, token_endpoint=tx.token_endpoint, client=client,
                                    code=code, verifier=tx.secret["code_verifier"],
                                    redirect_uri=tx.redirect_uri, resource=tx.resource)
    except McpError as err:
        return fail("failed", err.code, "failed")
    record = dict(token)
    record.update({"client_id": client.client_id, "client_secret": client.client_secret,
                   "token_endpoint_auth_method": method})
    public_meta = {"issuer": tx.issuer, "token_endpoint": tx.token_endpoint,
                   "resource": tx.resource, "client_id": client.client_id,
                   "token_endpoint_auth_method": method,
                   "revocation_endpoint": tx.binding_meta.get("revocation_endpoint"),
                   "scope": token.get("scope") or tx.binding_meta.get("scope"),
                   "client_registered": bool(tx.binding_meta.get("client_registered"))}
    try:
        result = svc.complete_oauth_transaction(tx.transaction_id, token=record, public_meta=public_meta)
    except McpError as err:
        return fail("failed", err.code, "failed")
    return {"outcome": "connected" if result == "succeeded" else "superseded",
            "transaction_id": tx.transaction_id}


# ---------------------------------------------------------------------------
# Central credential use and refresh
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _bearer(view: svc.CredentialView) -> dict[str, str]:
    return {"Authorization": f"Bearer {view.secret['access_token']}"}


def auth_headers(connector_pk: int, identity_generation: int, *, egress: Optional[Egress] = None,
                 sleep: Callable[[float], None] = time.sleep, force_refresh: bool = False
                 ) -> dict[str, str]:
    """Headers for one upstream request under a pinned identity, refreshing
    OAuth tokens centrally on demand. Never widens identity or policy."""
    view = svc.load_credential(connector_pk, identity_generation)
    if view.auth_mode == "none":
        return {}
    if view.auth_mode == "static":
        return dict(view.secret["headers"])
    expires = view.access_expires_at_unix
    if not force_refresh and (expires is None or expires > _now_ms() + REFRESH_SKEW_MS):
        return _bearer(view)
    return _refresh(view, egress or default_egress(), sleep)


def _refresh(view: svc.CredentialView, egress: Egress, sleep: Callable[[float], None]) -> dict[str, str]:
    start_revision = view.credential_revision
    for attempt in range(REFRESH_WAIT_ATTEMPTS):
        claim = svc.claim_refresh(view.connector_pk, identity_generation=view.identity_generation,
                                  credential_revision=view.credential_revision)
        if claim is None:
            # Another caller holds the slot or already refreshed: re-read.
            if attempt:
                sleep(remaining(REFRESH_WAIT_S))
            view = svc.load_credential(view.connector_pk, view.identity_generation)
            if view.credential_revision != start_revision:
                return _bearer(view)
            continue
        refresh_token = view.secret.get("refresh_token")
        if not refresh_token:
            svc.fail_refresh(view.connector_pk, claim=claim,
                             identity_generation=view.identity_generation, reconnect=True)
            raise McpError("reconnect_required", "authorization expired; reconnect the connector")
        client = oauth.OAuthClient(view.secret.get("client_id") or view.meta.get("client_id"),
                                   view.secret.get("client_secret"),
                                   view.secret.get("token_endpoint_auth_method") or "none")
        try:
            token = oauth.refresh(egress, token_endpoint=view.meta["token_endpoint"], client=client,
                                  refresh_token=refresh_token, resource=view.meta["resource"])
        except McpError as err:
            # Invalid grant, or an outcome we cannot know (a rotated refresh
            # token may have been issued): reconnect rather than race reuse.
            reconnect = err.code == "reconnect_required" or getattr(err, "uncertain", False)
            svc.fail_refresh(view.connector_pk, claim=claim,
                             identity_generation=view.identity_generation, reconnect=reconnect)
            if reconnect:
                raise McpError("reconnect_required", "authorization expired; reconnect the connector") from None
            raise
        if not svc.finalize_refresh(view.connector_pk, claim=claim,
                                    identity_generation=view.identity_generation,
                                    credential_revision=view.credential_revision, token=token):
            raise McpError("not_connected", "connector authorization was replaced or removed")
        return {"Authorization": f"Bearer {token['access_token']}"}
    raise McpError("provider_unavailable", "authorization refresh is in progress; retry")


# ---------------------------------------------------------------------------
# Discovery and lifecycle
# ---------------------------------------------------------------------------

def discover_tools(user_id: int, connector_id: str, *, egress: Optional[Egress] = None
                   ) -> dict[str, Any]:
    """Authenticated tools/list only; never executes a tool."""
    egress = egress or default_egress()
    binding = svc.connector_binding(user_id, connector_id)
    generation = binding["identity_generation"]
    client = None
    try:
        headers = auth_headers(binding["connector_pk"], generation, egress=egress)
        client = McpHttpClient(binding["endpoint"], headers, egress)
        tools = client.list_tools()
    except McpError as err:
        svc.record_test_failure(user_id, connector_id, identity_generation=generation,
                                error_code=err.code)
        raise
    finally:
        if client is not None:
            client.close()
    return svc.record_discovery(user_id, connector_id, identity_generation=generation, tools=tools)


def _revoke(material: Optional[dict], egress: Egress) -> str:
    if material is None:
        return "not_applicable"
    secret, meta = material["secret"], material["meta"]
    client = oauth.OAuthClient(secret.get("client_id") or meta.get("client_id"),
                               secret.get("client_secret"),
                               secret.get("token_endpoint_auth_method") or "none")
    endpoint = meta.get("revocation_endpoint")
    outcome = "not_supported"
    for token, hint in ((secret.get("refresh_token"), "refresh_token"),
                        (secret.get("access_token"), "access_token")):
        if token:
            outcome = oauth.revoke(egress, revocation_endpoint=endpoint, client=client,
                                   token=token, hint=hint)
            if outcome != "revoked":
                break
    return outcome


def _destroy(user_id: int, connector_id: str, action: Callable[[], dict], egress: Optional[Egress]
             ) -> dict[str, Any]:
    """Local destruction always proceeds; provider revocation is best effort
    after it and reported honestly."""
    try:
        material = svc.revocation_material(user_id, connector_id)
        revocation = None
    except McpError as err:
        if err.code != "key_unavailable":
            raise
        material, revocation = None, "skipped_key_unavailable"
    result = action()
    if revocation is None:
        revocation = _revoke(material, egress or default_egress())
    if revocation == "failed":
        logger.warning("mcp provider revocation failed connector={}", connector_id)
    result["revocation"] = revocation
    return result


def disconnect(user_id: int, connector_id: str, *, expected_revision: Any,
               egress: Optional[Egress] = None) -> dict[str, Any]:
    return _destroy(user_id, connector_id,
                    lambda: svc.disconnect(user_id, connector_id, expected_revision=expected_revision),
                    egress)


def delete(user_id: int, connector_id: str, *, expected_revision: Any,
           egress: Optional[Egress] = None) -> dict[str, Any]:
    return _destroy(user_id, connector_id,
                    lambda: svc.delete_connector(user_id, connector_id, expected_revision=expected_revision),
                    egress)
