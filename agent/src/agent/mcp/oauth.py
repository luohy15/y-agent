"""Standards-based OAuth for remote MCP servers (todo 3796).

Frozen v1 profile: RFC 9728 protected-resource metadata (WWW-Authenticate
`resource_metadata`, then the canonical well-known URLs), RFC 8414 metadata
with OIDC discovery fallback and an exact issuer match, RFC 7591 dynamic
registration when advertised or a manually registered client, authorization
code + S256 PKCE only, token endpoint auth `none` / `client_secret_basic` /
`client_secret_post`, and the RFC 8707 resource indicator. Anything else is
reported as `unsupported_oauth`, never approximated.

Provider responses are untrusted: only closed error codes leave this module,
never provider error descriptions, bodies or token values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, parse_qsl

from storage.service.mcp import McpError, TOKEN_AUTH_METHODS, validate_https_url
from agent.mcp.egress import Egress

MCP_PROTOCOL_VERSION = "2025-06-18"
_RESOURCE_METADATA_RE = re.compile(r'resource_metadata\s*=\s*"([^"]{1,2048})"', re.IGNORECASE)
_MAX_HEADER = 4096


@dataclass(frozen=True)
class ProviderMetadata:
    resource: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    revocation_endpoint: Optional[str] = None
    scopes_supported: tuple = ()
    resource_scopes_supported: tuple = ()
    token_endpoint_auth_methods_supported: tuple = ()
    iss_parameter_supported: bool = False


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: Optional[str]
    token_endpoint_auth_method: str
    registered: bool = False


class InvalidGrant(McpError):
    def __init__(self):
        super().__init__("reconnect_required", "authorization was rejected; reconnect the connector")


def _str_list(value: Any) -> tuple:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _path(url: str) -> str:
    path = urlsplit(url).path
    return "" if path in ("", "/") else path.rstrip("/")


def _same_resource(advertised: str, endpoint: str) -> bool:
    try:
        advertised = validate_https_url(advertised)
    except McpError:
        return False
    strip = lambda u: u.rstrip("/")  # noqa: E731
    return strip(advertised) in (strip(endpoint), strip(_origin(endpoint)))


def _fetch_json(egress: Egress, url: str) -> Optional[dict]:
    response = egress.get_metadata(url)
    if response.status in (404, 405, 410):
        return None
    if response.status != 200:
        raise McpError("unsupported_oauth", "provider authorization metadata is unavailable")
    body = response.json()
    if not isinstance(body, dict):
        raise McpError("unsupported_oauth", "provider authorization metadata is malformed")
    return body


def _probe_resource_metadata(egress: Egress, endpoint: str) -> Optional[str]:
    """An unauthenticated initialize; a 401 may point at the PRM document."""
    body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
        "clientInfo": {"name": "y-agent", "version": "1.0"}}}).encode()
    response = egress.request("POST", endpoint, content=body, allow_query=False, headers={
        "Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
    if response.status != 401:
        return None
    header = response.headers.get("www-authenticate", "")[:_MAX_HEADER]
    match = _RESOURCE_METADATA_RE.search(header)
    if not match:
        return None
    try:
        return validate_https_url(match.group(1), allow_query=True)
    except McpError:
        raise McpError("unsupported_oauth", "provider resource metadata URL is not permitted") from None


def discover(egress: Egress, endpoint: str) -> ProviderMetadata:
    endpoint = validate_https_url(endpoint)
    candidates = []
    hinted = _probe_resource_metadata(egress, endpoint)
    if hinted:
        candidates.append(hinted)
    origin, path = _origin(endpoint), _path(endpoint)
    if path:
        candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")
    prm = None
    for url in dict.fromkeys(candidates):
        prm = _fetch_json(egress, url)
        if prm is not None:
            break
    if prm is None:
        raise McpError("unsupported_oauth", "provider does not publish protected-resource metadata")
    resource = prm.get("resource")
    if not isinstance(resource, str) or not _same_resource(resource, endpoint):
        raise McpError("unsupported_oauth", "provider resource metadata does not match the endpoint")
    servers = _str_list(prm.get("authorization_servers"))
    if not servers:
        raise McpError("unsupported_oauth", "provider does not name an authorization server")
    issuer = servers[0]
    try:
        validate_https_url(issuer)
    except McpError:
        raise McpError("unsupported_oauth", "authorization server issuer is not permitted") from None
    meta = _authorization_server_metadata(egress, issuer)
    methods = _str_list(meta.get("code_challenge_methods_supported"))
    if "S256" not in methods:
        raise McpError("unsupported_oauth", "authorization server does not support S256 PKCE")
    response_types = _str_list(meta.get("response_types_supported"))
    if response_types and "code" not in response_types:
        raise McpError("unsupported_oauth", "authorization server does not support the code flow")
    grants = meta.get("grant_types_supported")
    if grants is not None and "authorization_code" not in _str_list(grants):
        raise McpError("unsupported_oauth", "authorization server does not support authorization_code")

    def endpoint_of(key: str, *, required: bool, allow_query: bool = False) -> Optional[str]:
        value = meta.get(key)
        if value is None and not required:
            return None
        try:
            return validate_https_url(value, allow_query=allow_query)
        except McpError:
            raise McpError("unsupported_oauth", f"authorization server {key} is not permitted") from None

    return ProviderMetadata(
        resource=validate_https_url(resource),
        issuer=issuer,
        authorization_endpoint=endpoint_of("authorization_endpoint", required=True, allow_query=True),
        token_endpoint=endpoint_of("token_endpoint", required=True),
        registration_endpoint=endpoint_of("registration_endpoint", required=False),
        revocation_endpoint=endpoint_of("revocation_endpoint", required=False),
        scopes_supported=_str_list(meta.get("scopes_supported")),
        resource_scopes_supported=_str_list(prm.get("scopes_supported")),
        token_endpoint_auth_methods_supported=_str_list(meta.get("token_endpoint_auth_methods_supported")),
        iss_parameter_supported=meta.get("authorization_response_iss_parameter_supported") is True,
    )


def _authorization_server_metadata(egress: Egress, issuer: str) -> dict:
    origin, path = _origin(issuer), _path(issuer)
    candidates = [f"{origin}/.well-known/oauth-authorization-server{path}",
                  f"{origin}/.well-known/openid-configuration{path}",
                  f"{issuer.rstrip('/')}/.well-known/openid-configuration"]
    for url in dict.fromkeys(candidates):
        meta = _fetch_json(egress, url)
        if meta is None:
            continue
        if meta.get("issuer") != issuer:
            # RFC 8414 section 3.3: a mismatched issuer is never usable.
            raise McpError("unsupported_oauth", "authorization server issuer does not match")
        return meta
    raise McpError("unsupported_oauth", "authorization server metadata is unavailable")


def select_scope(meta: ProviderMetadata, preset_scopes: tuple = ()) -> Optional[str]:
    advertised = set(meta.scopes_supported) | set(meta.resource_scopes_supported)
    if preset_scopes:
        chosen = [s for s in preset_scopes if not advertised or s in advertised]
        return " ".join(chosen) or None
    if meta.resource_scopes_supported:
        return " ".join(meta.resource_scopes_supported)
    return None


def choose_client(egress: Egress, meta: ProviderMetadata, redirect_uri: str,
                  manual: Optional[dict], scope: Optional[str]) -> OAuthClient:
    supported = meta.token_endpoint_auth_methods_supported or ("client_secret_basic",)
    if manual:
        method = manual.get("token_endpoint_auth_method") or "none"
        if meta.token_endpoint_auth_methods_supported and method not in supported:
            raise McpError("unsupported_oauth", "authorization server rejects the client authentication method")
        return OAuthClient(manual["client_id"], manual.get("client_secret"), method)
    if not meta.registration_endpoint:
        raise McpError("unsupported_oauth",
                       "provider has no dynamic registration; configure an OAuth client")
    method = next((m for m in ("none", "client_secret_basic", "client_secret_post") if m in supported), None)
    if method is None:
        raise McpError("unsupported_oauth", "no supported client authentication method")
    # A loopback redirect makes this a native client (RFC 8252 / OIDC DCR).
    request = {"client_name": "y-agent", "application_type": "native",
               "redirect_uris": [redirect_uri],
               "grant_types": ["authorization_code", "refresh_token"],
               "response_types": ["code"], "token_endpoint_auth_method": method}
    if scope:
        request["scope"] = scope
    response = egress.request("POST", meta.registration_endpoint, allow_query=False,
                              content=json.dumps(request).encode(),
                              headers={"Content-Type": "application/json", "Accept": "application/json"})
    if response.status not in (200, 201):
        raise McpError("unsupported_oauth", "dynamic client registration was rejected")
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("client_id"), str) or not body["client_id"]:
        raise McpError("protocol_error", "dynamic client registration response is malformed")
    registered_method = body.get("token_endpoint_auth_method") or method
    if registered_method not in TOKEN_AUTH_METHODS:
        raise McpError("unsupported_oauth", "registered client authentication method is unsupported")
    secret = body.get("client_secret") if isinstance(body.get("client_secret"), str) else None
    if registered_method != "none" and not secret:
        raise McpError("protocol_error", "dynamic client registration returned no secret")
    uris = body.get("redirect_uris")
    if uris is not None and redirect_uri not in _str_list(uris):
        raise McpError("unsupported_oauth", "provider did not register the callback URL")
    return OAuthClient(body["client_id"], secret, registered_method, registered=True)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(32)  # 256 random bits


def authorization_url(meta: ProviderMetadata, client: OAuthClient, *, redirect_uri: str,
                      state: str, challenge: str, scope: Optional[str]) -> str:
    parts = urlsplit(meta.authorization_endpoint)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if k not in ("response_type", "client_id", "redirect_uri", "state", "code_challenge",
                           "code_challenge_method", "resource", "scope")]
    params += [("response_type", "code"), ("client_id", client.client_id),
               ("redirect_uri", redirect_uri), ("state", state), ("code_challenge", challenge),
               ("code_challenge_method", "S256"), ("resource", meta.resource)]
    if scope:
        params.append(("scope", scope))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def _token_request(egress: Egress, token_endpoint: str, form: dict, client: OAuthClient) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    form = dict(form)
    if client.token_endpoint_auth_method == "client_secret_basic":
        raw = f"{quote(client.client_id, safe='')}:{quote(client.client_secret or '', safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode()
    elif client.token_endpoint_auth_method == "client_secret_post":
        form["client_id"] = client.client_id
        form["client_secret"] = client.client_secret or ""
    else:
        form["client_id"] = client.client_id
    response = egress.request("POST", token_endpoint, allow_query=False,
                              content=urlencode(form).encode(), headers=headers)
    if 300 <= response.status < 400:
        raise McpError("provider_error", "token endpoint redirected")
    if response.status in (400, 401):
        try:
            body = json.loads(response.body)
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("error") == "invalid_grant":
            raise InvalidGrant()
        raise McpError("auth_failed", "authorization server rejected the token request")
    if response.status >= 500 or response.status == 429:
        err = McpError("provider_unavailable", "authorization server is unavailable")
        err.uncertain = False
        raise err
    if response.status != 200:
        raise McpError("auth_failed", "authorization server rejected the token request")
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str) \
            or not body["access_token"]:
        raise McpError("protocol_error", "token response is malformed")
    if str(body.get("token_type", "")).lower() != "bearer":
        raise McpError("unsupported_oauth", "only bearer tokens are supported")
    expires_in = body.get("expires_in")
    expires_at = None
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool) and expires_in > 0:
        expires_at = int(time.time() * 1000) + int(expires_in * 1000)
    refresh = body.get("refresh_token") if isinstance(body.get("refresh_token"), str) else None
    return {"access_token": body["access_token"], "token_type": "Bearer",
            "refresh_token": refresh, "expires_at_unix": expires_at,
            "scope": body.get("scope") if isinstance(body.get("scope"), str) else None}


def exchange_code(egress: Egress, *, token_endpoint: str, client: OAuthClient, code: str,
                  verifier: str, redirect_uri: str, resource: str) -> dict:
    """Single attempt: an authorization code is never replayed."""
    return _token_request(egress, token_endpoint, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "code_verifier": verifier, "resource": resource}, client)


def refresh(egress: Egress, *, token_endpoint: str, client: OAuthClient, refresh_token: str,
            resource: str) -> dict:
    return _token_request(egress, token_endpoint, {
        "grant_type": "refresh_token", "refresh_token": refresh_token, "resource": resource}, client)


def revoke(egress: Egress, *, revocation_endpoint: Optional[str], client: OAuthClient,
           token: str, hint: str) -> str:
    """Best-effort RFC 7009 revocation: `revoked`, `failed` or `not_supported`."""
    if not revocation_endpoint:
        return "not_supported"
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        form = {"token": token, "token_type_hint": hint}
        if client.token_endpoint_auth_method == "client_secret_basic":
            raw = f"{quote(client.client_id, safe='')}:{quote(client.client_secret or '', safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode()
        else:
            form["client_id"] = client.client_id
            if client.token_endpoint_auth_method == "client_secret_post":
                form["client_secret"] = client.client_secret or ""
        response = egress.request("POST", revocation_endpoint, allow_query=False,
                                  content=urlencode(form).encode(), headers=headers)
    except McpError:
        return "failed"
    return "revoked" if response.status == 200 else "failed"
