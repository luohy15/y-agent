"""MCP connector state, credential custody and launch snapshots (todo 3796).

All functions take the internal owner id plus public identifiers; a guessed
connector/transaction/launch id of another owner is indistinguishable from a
missing one. Every management mutation takes the caller's expected
`config_revision` and increments it under the connector row lock.

Identity rule: changing the endpoint, auth mode, static headers, OAuth client,
disconnecting, or completing a reconnect over existing tokens increments
`identity_generation`, destroys every stored credential, supersedes pending
OAuth transactions and clears discovery, validation, approval and desired
enablement. Old launches pinned to the previous generation are denied. Rename
and approval edits do not change identity.

Secret material is only ever sealed through `mcp_crypto`; projections returned
here never contain it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

from storage.database.base import get_db
from storage.entity.mcp import (
    McpConnectorEntity, McpCredentialEntity, McpLaunchConnectorEntity, McpLaunchEntity,
    McpOAuthTransactionEntity,
)
from storage.repository import mcp as repo
from storage.service import mcp_crypto as crypto
from storage.util import get_unix_timestamp

# ---------------------------------------------------------------------------
# Bounds and presets
# ---------------------------------------------------------------------------

MAX_CONNECTORS_PER_OWNER = 50
MAX_CONNECTORS_PER_LAUNCH = 10
MAX_TOOLS = 1000
MAX_NAME = 64
MAX_URL = 2048
MAX_TOOL_NAME = 128
MAX_DESCRIPTION = 2000
MAX_SCHEMA_BYTES = 64 * 1024
MAX_SECRET_BYTES = 32 * 1024
MAX_STATIC_HEADERS = 16
MAX_CLIENT_ID = 512

OAUTH_TRANSACTION_TTL_MS = 10 * 60 * 1000
REFRESH_CLAIM_TTL_MS = 30 * 1000
LAUNCH_IDLE_TTL_MS = 30 * 60 * 1000
LAUNCH_RETENTION_MS = 7 * 24 * 3600 * 1000
TRANSACTION_RETENTION_MS = 24 * 3600 * 1000

AUTH_MODES = ("oauth", "static", "none")
TOKEN_AUTH_METHODS = ("none", "client_secret_basic", "client_secret_post")

PRESETS: dict[str, dict[str, Any]] = {
    "alphavantage": {
        "name": "Alpha Vantage",
        "endpoint": "https://mcp.alphavantage.co/mcp",
        "auth_modes": ("oauth", "static"),
        "default_auth_mode": "oauth",
        "scopes": ("alphavantage:read",),
        "static_header": "apikey",
        # Legacy meta-dispatch tools would let one approved name invoke any
        # other tool; the preset supports flat tools only.
        "excluded_tools": frozenset({"TOOL_LIST", "TOOL_GET", "TOOL_CALL"}),
    },
}

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,128}$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
_FORBIDDEN_HEADERS = frozenset({
    "host", "cookie", "set-cookie", "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authorization", "proxy-authenticate", "proxy-connection", "te",
    "trailer", "upgrade", "accept", "content-type", "mcp-session-id", "mcp-protocol-version",
    "last-event-id", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip",
})
_ANNOTATION_KEYS = ("title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


# ---------------------------------------------------------------------------
# Errors (closed codes, safe messages)
# ---------------------------------------------------------------------------

class McpError(Exception):
    """A closed error code plus a safe user message; never provider content."""

    STATUS = {
        "invalid_input": 400, "not_found": 404, "conflict": 409, "forbidden": 403,
        "not_ready": 409, "key_unavailable": 503, "reconnect_required": 409,
        "not_connected": 409, "oauth_state_invalid": 400, "oauth_state_expired": 400,
        "unsupported_oauth": 422, "network_blocked": 422, "timeout": 504,
        "response_too_large": 502, "protocol_error": 502, "provider_error": 502,
        "provider_unavailable": 503, "auth_failed": 502,
    }

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code if code in self.STATUS else "provider_error"
        self.message = message

    @property
    def status(self) -> int:
        return self.STATUS[self.code]

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _now() -> int:
    return get_unix_timestamp()


def require_maintainer(user_id: int) -> None:
    """Fail closed unless the configured module maintainer is this owner."""
    from storage.service.user import get_module_maintainer_user_id

    maintainer = get_module_maintainer_user_id()
    if maintainer is None or maintainer != user_id:
        raise McpError("forbidden", "MCP connectors are restricted to the configured maintainer")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_https_url(url: Any, *, allow_query: bool = False) -> str:
    """Syntactic egress rule shared by endpoints and discovered OAuth URLs.

    HTTPS only, a hostname, no userinfo, no fragment and (for connector
    endpoints) no query string, so a credential can never ride in the URL.
    Address resolution and pinning are enforced at dial time by the host
    egress client.
    """
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        raise McpError("invalid_input", "URL must be a non-empty HTTPS URL")
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url):
        raise McpError("invalid_input", "URL must not contain whitespace or control characters")
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise McpError("invalid_input", "only HTTPS URLs are supported")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise McpError("invalid_input", "URL must not contain credentials")
    if parts.fragment or "#" in url:
        raise McpError("invalid_input", "URL must not contain a fragment")
    if parts.query and not allow_query:
        raise McpError("invalid_input", "endpoint URL must not contain a query string")
    host = parts.hostname
    if not host:
        raise McpError("invalid_input", "URL must include a host")
    try:
        port = parts.port
        host.encode("idna")
    except (ValueError, UnicodeError):
        raise McpError("invalid_input", "URL host or port is invalid") from None
    netloc = host if ":" not in host else f"[{host}]"
    if port is not None and port != 443:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise McpError("invalid_input", "name is required")
    name = name.strip()
    if len(name) > MAX_NAME or any(ord(ch) < 0x20 for ch in name):
        raise McpError("invalid_input", f"name must be at most {MAX_NAME} printable characters")
    return name


def validate_static_headers(headers: Any, *, preset: Optional[str] = None) -> dict[str, str]:
    if not isinstance(headers, dict) or not headers:
        raise McpError("invalid_input", "static headers must be a non-empty mapping")
    if len(headers) > MAX_STATIC_HEADERS:
        raise McpError("invalid_input", f"at most {MAX_STATIC_HEADERS} static headers")
    out: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or not _HEADER_NAME_RE.match(name):
            raise McpError("invalid_input", "header names must be HTTP tokens")
        lower = name.lower()
        if lower in _FORBIDDEN_HEADERS or lower.startswith("proxy-"):
            raise McpError("invalid_input", f"header {name} is not allowed")
        if lower in seen:
            raise McpError("invalid_input", "duplicate header name")
        seen.add(lower)
        if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n\x00"):
            raise McpError("invalid_input", "header values must be non-empty single-line text")
        out[name] = value
    if len(json.dumps(out).encode()) > MAX_SECRET_BYTES:
        raise McpError("invalid_input", "static headers are too large")
    return out


def _preset(row_or_name) -> Optional[dict[str, Any]]:
    name = row_or_name if isinstance(row_or_name, (str, type(None))) else row_or_name.preset
    return PRESETS.get(name) if name else None


def normalize_tools(tools: Any, *, preset: Optional[str] = None) -> list[dict[str, Any]]:
    """Bound and sanitize an untrusted provider tool list for the catalog."""
    if not isinstance(tools, list):
        raise McpError("protocol_error", "provider returned a malformed tool list")
    if len(tools) > MAX_TOOLS:
        raise McpError("response_too_large", f"provider returned more than {MAX_TOOLS} tools")
    excluded = (_preset(preset) or {}).get("excluded_tools", frozenset())
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise McpError("protocol_error", "provider returned a malformed tool")
        name = tool.get("name")
        if not isinstance(name, str) or not _TOOL_NAME_RE.match(name):
            raise McpError("protocol_error", "provider returned an invalid tool name")
        if name in excluded or name in seen:
            continue
        seen.add(name)
        description = tool.get("description")
        description = description[:MAX_DESCRIPTION] if isinstance(description, str) else ""
        raw_annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        annotations = {
            key: raw_annotations[key] for key in _ANNOTATION_KEYS
            if isinstance(raw_annotations.get(key), (bool, str))
            and (key != "title" or len(raw_annotations[key]) <= MAX_NAME * 2)
        }
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object"}
        if len(json.dumps(schema).encode()) > MAX_SCHEMA_BYTES:
            raise McpError("response_too_large", "provider tool schema is too large")
        out.append({"name": name, "description": description, "annotations": annotations,
                    "inputSchema": schema})
    return out


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def _json_list(raw: Optional[str]) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw: Optional[str]) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _auth_ready(session, row: McpConnectorEntity) -> bool:
    if row.auth_mode == "none":
        return True
    kind = "static_headers" if row.auth_mode == "static" else "oauth_token"
    cred = repo.get_credential(session, row.id, kind)
    return bool(cred and cred.identity_generation == row.identity_generation
                and cred.status == "usable")


def _refresh_auth_state(session, row: McpConnectorEntity) -> None:
    if row.auth_mode == "none":
        row.auth_state = "not_required"
        return
    kind = "static_headers" if row.auth_mode == "static" else "oauth_token"
    cred = repo.get_credential(session, row.id, kind)
    if cred is None or cred.identity_generation != row.identity_generation:
        row.auth_state = "not_configured"
    elif cred.status != "usable":
        row.auth_state = "reconnect_required"
    else:
        row.auth_state = "connected"


def _blocking(session, row: McpConnectorEntity) -> list[str]:
    reasons = []
    if not _auth_ready(session, row):
        reasons.append("reconnect_required" if row.auth_state == "reconnect_required"
                       else "authentication_required")
    if row.validated_identity_generation != row.identity_generation:
        reasons.append("validation_required")
    if not _json_list(row.approved_tools):
        reasons.append("tool_approval_required")
    return reasons


def _connector_dict(session, row: McpConnectorEntity) -> dict[str, Any]:
    approved = _json_list(row.approved_tools)
    catalog = _json_list(row.catalog)
    catalog_names = {tool["name"] for tool in catalog}
    tools = [{"name": tool["name"], "description": tool.get("description", ""),
              "annotations": tool.get("annotations", {}),
              "approved": tool["name"] in approved, "available": True} for tool in catalog]
    tools += [{"name": name, "description": "", "annotations": {}, "approved": True,
               "available": False} for name in approved if name not in catalog_names]
    blocking = _blocking(session, row)
    out: dict[str, Any] = {
        "connector_id": row.connector_id,
        "name": row.name,
        "endpoint": row.endpoint,
        "preset": row.preset,
        "auth_mode": row.auth_mode,
        "desired_enabled": bool(row.desired_enabled),
        "config_revision": row.config_revision,
        "identity_generation": row.identity_generation,
        "discovery_revision": row.discovery_revision,
        "validated": row.validated_identity_generation == row.identity_generation,
        "auth_state": row.auth_state,
        "auth_ready": _auth_ready(session, row),
        "ready_to_enable": not blocking,
        "blocking": blocking,
        "approved_tools": approved,
        "tools": tools,
        "last_test": {"at_unix": row.last_test_at_unix, "status": row.last_test_status,
                      "error_code": row.last_test_error_code},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if row.auth_mode == "static":
        cred = repo.get_credential(session, row.id, "static_headers")
        out["static_header_names"] = _json_dict(cred.public_meta).get("header_names", []) if cred else []
    if row.auth_mode == "oauth":
        client = repo.get_credential(session, row.id, "oauth_client")
        token = repo.get_credential(session, row.id, "oauth_token")
        client_meta = _json_dict(client.public_meta) if client else {}
        token_meta = _json_dict(token.public_meta) if token else {}
        out["oauth"] = {
            "client_mode": "manual" if client else "dynamic",
            "client_id": client_meta.get("client_id"),
            "token_endpoint_auth_method": client_meta.get("token_endpoint_auth_method"),
            "has_client_secret": bool(client_meta.get("has_client_secret")),
            "issuer": token_meta.get("issuer"),
            "scope": token_meta.get("scope"),
            "access_expires_at_unix": token.access_expires_at_unix if token else None,
        }
    return out


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _load(session, user_id: int, connector_id: Any, *, lock: bool = True) -> McpConnectorEntity:
    if not isinstance(connector_id, str) or not connector_id:
        raise McpError("not_found", "connector not found")
    row = repo.get_live_connector(session, user_id, connector_id, lock=lock)
    if row is None:
        raise McpError("not_found", "connector not found")
    return row


def _check_revision(row: McpConnectorEntity, expected: Any) -> None:
    if not isinstance(expected, int) or isinstance(expected, bool) or expected != row.config_revision:
        raise McpError("conflict", "connector changed; reload and retry")


def _bump(row: McpConnectorEntity) -> None:
    row.config_revision = (row.config_revision or 0) + 1


def _identity_change(session, row: McpConnectorEntity) -> None:
    """New server/auth identity: nothing validated or approved carries over."""
    row.identity_generation = (row.identity_generation or 0) + 1
    row.approved_tools = "[]"
    row.catalog = None
    row.discovery_revision = (row.discovery_revision or 0) + 1
    row.validated_identity_generation = None
    row.desired_enabled = False
    row.last_test_at_unix = None
    row.last_test_status = None
    row.last_test_error_code = None
    repo.delete_credentials(session, row.id, ("static_headers", "oauth_client", "oauth_token"))
    repo.supersede_pending_transactions(session, row.id)


def _context(session, row: McpConnectorEntity, kind: str) -> dict[str, str]:
    owner = repo.public_user_id(session, row.user_id)
    return crypto.crypto_context(owner, row.connector_id, row.identity_generation, kind)


def _put_credential(session, row: McpConnectorEntity, kind: str, secret: dict, public_meta: dict,
                    *, access_expires_at_unix: Optional[int] = None) -> McpCredentialEntity:
    envelope = crypto.seal(secret, _context(session, row, kind))
    cred = repo.get_credential(session, row.id, kind, lock=True)
    if cred is None:
        cred = McpCredentialEntity(connector_pk=row.id, kind=kind)
        session.add(cred)
    crypto.store_envelope(cred, envelope)
    cred.identity_generation = row.identity_generation
    cred.public_meta = json.dumps(public_meta)
    cred.access_expires_at_unix = access_expires_at_unix
    cred.credential_revision = (cred.credential_revision or 0) + 1
    cred.status = "usable"
    cred.refresh_claim = None
    cred.refresh_claim_deadline_unix = None
    return cred


def _open_credential(session, row: McpConnectorEntity, cred: McpCredentialEntity) -> dict:
    if cred.identity_generation != row.identity_generation:
        raise McpError("not_connected", "credential belongs to a replaced identity")
    context = crypto.crypto_context(repo.public_user_id(session, row.user_id), row.connector_id,
                                    cred.identity_generation, cred.kind)
    try:
        return crypto.open_envelope(crypto.envelope_of(cred), context)
    except crypto.McpKeyUnavailable:
        raise McpError("key_unavailable", "credential key is unavailable; access denied") from None
    except crypto.McpCiphertextInvalid:
        raise McpError("key_unavailable", "stored credential cannot be decrypted; reconnect") from None


def _sealing(fn):
    """Map key-provider failures during sealing to the closed error code."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except crypto.McpKeyUnavailable:
            raise McpError("key_unavailable", "credential key is unavailable") from None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

def list_connectors(user_id: int) -> list[dict[str, Any]]:
    with get_db() as session:
        return [_connector_dict(session, row) for row in repo.list_live_connectors(session, user_id)]


def get_connector(user_id: int, connector_id: str) -> dict[str, Any]:
    with get_db() as session:
        return _connector_dict(session, _load(session, user_id, connector_id, lock=False))


def list_presets() -> list[dict[str, Any]]:
    return [{"preset": key, "name": p["name"], "endpoint": p["endpoint"],
             "auth_modes": list(p["auth_modes"]), "default_auth_mode": p["default_auth_mode"],
             "scopes": list(p["scopes"]), "static_header": p["static_header"]}
            for key, p in PRESETS.items()]


def create_connector(user_id: int, *, name: Any, endpoint: Any = None, auth_mode: Any = None,
                     preset: Any = None) -> dict[str, Any]:
    preset_def = None
    if preset is not None:
        preset_def = PRESETS.get(preset) if isinstance(preset, str) else None
        if preset_def is None:
            raise McpError("invalid_input", "unknown preset")
        endpoint = endpoint or preset_def["endpoint"]
        auth_mode = auth_mode or preset_def["default_auth_mode"]
    endpoint = validate_https_url(endpoint)
    if preset_def and endpoint != validate_https_url(preset_def["endpoint"]):
        raise McpError("invalid_input", "preset endpoint is fixed")
    if auth_mode not in AUTH_MODES or (preset_def and auth_mode not in preset_def["auth_modes"]):
        raise McpError("invalid_input", "unsupported authentication mode")
    name = _validate_name(name)
    with get_db() as session:
        if len(repo.list_live_connectors(session, user_id)) >= MAX_CONNECTORS_PER_OWNER:
            raise McpError("invalid_input", "connector limit reached")
        if repo.live_name_taken(session, user_id, name):
            raise McpError("conflict", "a connector with this name already exists")
        row = McpConnectorEntity(
            connector_id=str(uuid.uuid4()), user_id=user_id, name=name, endpoint=endpoint,
            preset=preset, auth_mode=auth_mode, desired_enabled=False, config_revision=1,
            identity_generation=1, approved_tools="[]", discovery_revision=0,
            auth_state="not_required" if auth_mode == "none" else "not_configured",
        )
        session.add(row)
        session.flush()
        return _connector_dict(session, row)


def update_connector(user_id: int, connector_id: str, *, expected_revision: Any, name: Any = None,
                     endpoint: Any = None, auth_mode: Any = None) -> dict[str, Any]:
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        preset_def = _preset(row)
        identity_changed = False
        if name is not None:
            name = _validate_name(name)
            if repo.live_name_taken(session, user_id, name, exclude_pk=row.id):
                raise McpError("conflict", "a connector with this name already exists")
            row.name = name
        if endpoint is not None:
            endpoint = validate_https_url(endpoint)
            if endpoint != row.endpoint:
                if preset_def:
                    raise McpError("invalid_input", "preset endpoint is fixed")
                row.endpoint = endpoint
                identity_changed = True
        if auth_mode is not None and auth_mode != row.auth_mode:
            if auth_mode not in AUTH_MODES or (preset_def and auth_mode not in preset_def["auth_modes"]):
                raise McpError("invalid_input", "unsupported authentication mode")
            row.auth_mode = auth_mode
            identity_changed = True
        if identity_changed:
            _identity_change(session, row)
        _refresh_auth_state(session, row)
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


def set_enabled(user_id: int, connector_id: str, *, expected_revision: Any, enabled: Any
                ) -> dict[str, Any]:
    if not isinstance(enabled, bool):
        raise McpError("invalid_input", "enabled must be a boolean")
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        if enabled:
            blocking = _blocking(session, row)
            if blocking:
                raise McpError("not_ready", "connector cannot be enabled: " + ", ".join(blocking))
        row.desired_enabled = enabled
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


@_sealing
def set_static_headers(user_id: int, connector_id: str, *, expected_revision: Any,
                       headers: Optional[dict]) -> dict[str, Any]:
    """Replace (or clear with None) the write-only static header credential."""
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        if row.auth_mode != "static":
            raise McpError("invalid_input", "connector does not use static header authentication")
        validated = None if headers is None else validate_static_headers(headers, preset=row.preset)
        _identity_change(session, row)
        if validated is not None:
            _put_credential(session, row, "static_headers", {"headers": validated},
                            {"header_names": sorted(validated)})
        _refresh_auth_state(session, row)
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


@_sealing
def set_oauth_client(user_id: int, connector_id: str, *, expected_revision: Any,
                     client_id: Optional[str], client_secret: Optional[str] = None,
                     token_endpoint_auth_method: Optional[str] = None) -> dict[str, Any]:
    """Store a manually registered OAuth client, or clear it (None) to use
    dynamic client registration. Either way the identity is replaced."""
    if client_id is not None:
        if not isinstance(client_id, str) or not client_id or len(client_id) > MAX_CLIENT_ID \
                or any(ord(ch) < 0x21 for ch in client_id):
            raise McpError("invalid_input", "client_id is invalid")
        method = token_endpoint_auth_method or ("client_secret_basic" if client_secret else "none")
        if method not in TOKEN_AUTH_METHODS:
            raise McpError("invalid_input", "unsupported token endpoint authentication method")
        if (method == "none") != (not client_secret):
            raise McpError("invalid_input", "client secret must match the authentication method")
        if client_secret is not None and (not isinstance(client_secret, str)
                                          or len(client_secret.encode()) > MAX_SECRET_BYTES
                                          or any(ch in client_secret for ch in "\r\n\x00")):
            raise McpError("invalid_input", "client secret is invalid")
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        if row.auth_mode != "oauth":
            raise McpError("invalid_input", "connector does not use OAuth")
        _identity_change(session, row)
        if client_id is not None:
            _put_credential(session, row, "oauth_client",
                            {"client_id": client_id, "client_secret": client_secret},
                            {"client_id": client_id, "token_endpoint_auth_method": method,
                             "has_client_secret": bool(client_secret)})
        _refresh_auth_state(session, row)
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


def set_approved_tools(user_id: int, connector_id: str, *, expected_revision: Any,
                       discovery_revision: Any, tools: Optional[Iterable[str]] = None,
                       select_all: bool = False) -> dict[str, Any]:
    """Explicit approval against the discovery snapshot the caller saw.
    `select_all` expands to exactly that snapshot's names, never future ones."""
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        if discovery_revision != row.discovery_revision:
            raise McpError("conflict", "tool discovery changed; review the current tool list")
        if row.validated_identity_generation != row.identity_generation:
            raise McpError("not_ready", "discover tools before approving them")
        catalog_names = [tool["name"] for tool in _json_list(row.catalog)]
        if select_all:
            names = list(catalog_names)
        else:
            if tools is None or isinstance(tools, (str, bytes)):
                raise McpError("invalid_input", "tools must be a list of tool names")
            names = list(tools)
            unknown = [n for n in names if not isinstance(n, str) or n not in catalog_names]
            if unknown:
                raise McpError("invalid_input", "only currently discovered tools can be approved")
        row.approved_tools = json.dumps(sorted(set(names)))
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


def record_discovery(user_id: int, connector_id: str, *, identity_generation: int,
                     tools: Any) -> dict[str, Any]:
    """Persist an authenticated discovery observation for the identity it ran
    under; a result for a replaced identity is discarded (conflict)."""
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        if row.identity_generation != identity_generation:
            raise McpError("conflict", "connector identity changed during discovery")
        row.catalog = json.dumps(normalize_tools(tools, preset=row.preset))
        row.discovery_revision = (row.discovery_revision or 0) + 1
        row.validated_identity_generation = identity_generation
        row.last_test_at_unix = _now()
        row.last_test_status = "ok"
        row.last_test_error_code = None
        session.flush()
        return _connector_dict(session, row)


def record_test_failure(user_id: int, connector_id: str, *, identity_generation: int,
                        error_code: str) -> None:
    with get_db() as session:
        row = repo.get_live_connector(session, user_id, connector_id, lock=True)
        if row is None or row.identity_generation != identity_generation:
            return
        row.last_test_at_unix = _now()
        row.last_test_status = "failed"
        row.last_test_error_code = error_code if error_code in McpError.STATUS else "provider_error"


def disconnect(user_id: int, connector_id: str, *, expected_revision: Any) -> dict[str, Any]:
    """Destroy every reusable credential; reconnecting starts a new identity."""
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        _identity_change(session, row)
        _refresh_auth_state(session, row)
        _bump(row)
        session.flush()
        return _connector_dict(session, row)


def delete_connector(user_id: int, connector_id: str, *, expected_revision: Any) -> dict[str, Any]:
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        _check_revision(row, expected_revision)
        _identity_change(session, row)
        row.deleted_at_unix = _now()
        _bump(row)
        session.flush()
        return {"connector_id": row.connector_id, "deleted": True}


def revocation_material(user_id: int, connector_id: str) -> Optional[dict[str, Any]]:
    """Decrypted OAuth token + binding for best-effort provider revocation
    before a local destroy. None when there is nothing to revoke; raises
    `key_unavailable` rather than guessing."""
    with get_db() as session:
        row = _load(session, user_id, connector_id, lock=False)
        if row.auth_mode != "oauth":
            return None
        cred = repo.get_credential(session, row.id, "oauth_token")
        if cred is None or cred.identity_generation != row.identity_generation:
            return None
        secret = _open_credential(session, row, cred)
        return {"secret": secret, "meta": _json_dict(cred.public_meta)}


# ---------------------------------------------------------------------------
# OAuth transactions
# ---------------------------------------------------------------------------

def state_digest(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


@dataclass(frozen=True)
class ConsumedTransaction:
    transaction_id: str
    user_id: int
    connector_id: str
    preset: Optional[str]
    endpoint: str
    identity_generation: int
    issuer: str
    resource: str
    redirect_uri: str
    client_id: str
    token_endpoint: str
    binding_meta: dict
    secret: dict


def oauth_client_material(user_id: int, connector_id: str) -> dict[str, Any]:
    """Connector binding needed to start an authorization: endpoint, preset,
    identity generation and the manual client (decrypted) if one is set."""
    with get_db() as session:
        row = _load(session, user_id, connector_id, lock=False)
        if row.auth_mode != "oauth":
            raise McpError("invalid_input", "connector does not use OAuth")
        client = repo.get_credential(session, row.id, "oauth_client")
        manual = None
        if client is not None:
            secret = _open_credential(session, row, client)
            meta = _json_dict(client.public_meta)
            manual = {"client_id": secret["client_id"], "client_secret": secret.get("client_secret"),
                      "token_endpoint_auth_method": meta.get("token_endpoint_auth_method", "none")}
        return {"endpoint": row.endpoint, "preset": row.preset,
                "identity_generation": row.identity_generation, "manual_client": manual}


@_sealing
def begin_oauth_transaction(user_id: int, connector_id: str, *, identity_generation: int,
                            state: str, secret: dict, issuer: str, resource: str,
                            redirect_uri: str, client_id: str, token_endpoint: str,
                            binding_meta: dict) -> dict[str, Any]:
    now = _now()
    with get_db() as session:
        row = _load(session, user_id, connector_id)
        if row.auth_mode != "oauth":
            raise McpError("invalid_input", "connector does not use OAuth")
        if row.identity_generation != identity_generation:
            raise McpError("conflict", "connector changed while preparing authorization")
        transaction_id = str(uuid.uuid4())
        owner = repo.public_user_id(session, user_id)
        envelope = crypto.seal(secret, crypto.crypto_context(
            owner, row.connector_id, identity_generation, f"oauth_transaction:{transaction_id}"))
        tx = McpOAuthTransactionEntity(
            transaction_id=transaction_id, user_id=user_id, connector_pk=row.id,
            identity_generation=identity_generation, state_hash=state_digest(state),
            issuer=issuer, resource=resource, redirect_uri=redirect_uri, client_id=client_id,
            token_endpoint=token_endpoint, binding_meta=json.dumps(binding_meta),
            expires_at_unix=now + OAUTH_TRANSACTION_TTL_MS, status="pending",
        )
        crypto.store_envelope(tx, envelope)
        session.add(tx)
        session.flush()
        return {"transaction_id": transaction_id, "expires_at_unix": tx.expires_at_unix}


def consume_oauth_state(state: Any) -> ConsumedTransaction:
    """Atomically consume a callback state (single use, even on denial).

    Raises `oauth_state_invalid` for unknown/replayed/superseded state and
    `oauth_state_expired` past the 10-minute window; the transaction is
    marked terminal in its own committed transaction before the raise.
    """
    if not isinstance(state, str) or not state or len(state) > 512:
        raise McpError("oauth_state_invalid", "authorization state is invalid")
    now = _now()
    failure: Optional[McpError] = None
    result: Optional[ConsumedTransaction] = None
    with get_db() as session:
        tx = repo.get_transaction_by_state(session, state_digest(state), lock=True)
        if tx is None or tx.status != "pending":
            raise McpError("oauth_state_invalid", "authorization state is invalid or already used")
        tx.consumed_at_unix = now
        row = repo.get_connector_by_pk(session, tx.connector_pk)
        if tx.expires_at_unix <= now:
            tx.status, tx.error_code = "expired", "oauth_state_expired"
            failure = McpError("oauth_state_expired", "authorization expired; connect again")
        elif row is None or row.deleted_at_unix is not None \
                or row.identity_generation != tx.identity_generation:
            tx.status, tx.error_code = "superseded", "oauth_state_invalid"
            failure = McpError("oauth_state_invalid", "connector changed; connect again")
        else:
            owner = repo.public_user_id(session, tx.user_id)
            try:
                secret = crypto.open_envelope(crypto.envelope_of(tx), crypto.crypto_context(
                    owner, row.connector_id, tx.identity_generation,
                    f"oauth_transaction:{tx.transaction_id}"))
            except (crypto.McpKeyUnavailable, crypto.McpCiphertextInvalid):
                tx.status, tx.error_code = "failed", "key_unavailable"
                failure = McpError("key_unavailable", "credential key is unavailable")
            else:
                tx.status = "exchanging"
                result = ConsumedTransaction(
                    transaction_id=tx.transaction_id, user_id=tx.user_id,
                    connector_id=row.connector_id, preset=row.preset, endpoint=row.endpoint,
                    identity_generation=tx.identity_generation, issuer=tx.issuer,
                    resource=tx.resource, redirect_uri=tx.redirect_uri, client_id=tx.client_id,
                    token_endpoint=tx.token_endpoint, binding_meta=_json_dict(tx.binding_meta),
                    secret=secret,
                )
    if failure is not None:
        raise failure
    return result


def fail_oauth_transaction(transaction_id: str, *, status: str, error_code: str) -> None:
    if status not in ("denied", "failed"):
        status = "failed"
    with get_db() as session:
        tx = repo.get_transaction(session, transaction_id, lock=True)
        if tx is not None and tx.status in ("pending", "exchanging"):
            tx.status = status
            tx.error_code = error_code if error_code in McpError.STATUS or error_code == "access_denied" \
                else "provider_error"


@_sealing
def complete_oauth_transaction(transaction_id: str, *, token: dict, public_meta: dict) -> str:
    """Store exchanged tokens only if the transaction and connector identity
    are still current; otherwise discard them. Returns `succeeded` or
    `superseded`. Completing over existing tokens replaces the identity."""
    with get_db() as session:
        tx = repo.get_transaction(session, transaction_id)
        if tx is None:
            return "superseded"
        row = repo.get_connector_by_pk(session, tx.connector_pk, lock=True)
        tx = repo.get_transaction(session, transaction_id, lock=True)
        if tx.status != "exchanging" or row is None or row.deleted_at_unix is not None \
                or row.identity_generation != tx.identity_generation or row.auth_mode != "oauth":
            if tx.status in ("pending", "exchanging"):
                tx.status, tx.error_code = "superseded", "oauth_state_invalid"
            return "superseded"
        existing = repo.get_credential(session, row.id, "oauth_token")
        if existing is not None:
            manual = repo.get_credential(session, row.id, "oauth_client")
            manual_secret = _open_credential(session, row, manual) if manual else None
            manual_meta = _json_dict(manual.public_meta) if manual else None
            _identity_change(session, row)
            if manual_secret is not None:
                _put_credential(session, row, "oauth_client", manual_secret, manual_meta)
            _bump(row)
        _put_credential(session, row, "oauth_token", token, public_meta,
                        access_expires_at_unix=token.get("expires_at_unix"))
        _refresh_auth_state(session, row)
        tx.status = "succeeded"
        tx.error_code = None
        return "succeeded"


def get_oauth_status(user_id: int, transaction_id: Any) -> dict[str, Any]:
    if not isinstance(transaction_id, str) or not transaction_id:
        raise McpError("not_found", "authorization not found")
    now = _now()
    with get_db() as session:
        tx = repo.get_transaction(session, transaction_id, user_id=user_id)
        if tx is None:
            raise McpError("not_found", "authorization not found")
        row = repo.get_connector_by_pk(session, tx.connector_pk)
        status = tx.status
        if status == "pending" and tx.expires_at_unix <= now:
            status = "expired"
        return {"transaction_id": tx.transaction_id,
                "connector_id": row.connector_id if row else None,
                "status": status, "error_code": tx.error_code,
                "expires_at_unix": tx.expires_at_unix}


# ---------------------------------------------------------------------------
# Central credential access and refresh
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CredentialView:
    connector_pk: int
    connector_id: str
    identity_generation: int
    auth_mode: str
    kind: Optional[str]
    credential_revision: int
    secret: dict
    meta: dict
    access_expires_at_unix: Optional[int]


def load_credential(connector_pk: int, identity_generation: int) -> CredentialView:
    """Decrypt the usable credential for a pinned identity (API role only)."""
    with get_db() as session:
        row = repo.get_connector_by_pk(session, connector_pk)
        if row is None or row.deleted_at_unix is not None \
                or row.identity_generation != identity_generation:
            raise McpError("not_connected", "connector authorization was replaced or removed")
        if row.auth_mode == "none":
            return CredentialView(row.id, row.connector_id, identity_generation, "none", None, 0,
                                  {}, {}, None)
        kind = "static_headers" if row.auth_mode == "static" else "oauth_token"
        cred = repo.get_credential(session, row.id, kind)
        if cred is None or cred.identity_generation != identity_generation:
            raise McpError("not_connected", "connector is not connected")
        if cred.status != "usable":
            raise McpError("reconnect_required", "authorization expired; reconnect the connector")
        return CredentialView(row.id, row.connector_id, identity_generation, row.auth_mode, kind,
                              cred.credential_revision, _open_credential(session, row, cred),
                              _json_dict(cred.public_meta), cred.access_expires_at_unix)


def connector_binding(user_id: int, connector_id: str) -> dict[str, Any]:
    """Internal binding for host network operations (never returned to callers)."""
    with get_db() as session:
        row = _load(session, user_id, connector_id, lock=False)
        return {"connector_pk": row.id, "identity_generation": row.identity_generation,
                "endpoint": row.endpoint, "preset": row.preset, "auth_mode": row.auth_mode}


def claim_refresh(connector_pk: int, *, identity_generation: int, credential_revision: int
                  ) -> Optional[str]:
    """Reserve the single refresh slot for this credential revision.

    None means another caller holds a live claim or already refreshed
    (re-read the credential). Network I/O happens outside this transaction.
    """
    now = _now()
    with get_db() as session:
        row = repo.get_connector_by_pk(session, connector_pk, lock=True)
        if row is None or row.deleted_at_unix is not None \
                or row.identity_generation != identity_generation:
            raise McpError("not_connected", "connector authorization was replaced or removed")
        cred = repo.get_credential(session, connector_pk, "oauth_token", lock=True)
        if cred is None or cred.identity_generation != identity_generation:
            raise McpError("not_connected", "connector is not connected")
        if cred.status != "usable":
            raise McpError("reconnect_required", "authorization expired; reconnect the connector")
        if cred.credential_revision != credential_revision:
            return None
        if cred.refresh_claim and (cred.refresh_claim_deadline_unix or 0) > now:
            return None
        claim = str(uuid.uuid4())
        cred.refresh_claim = claim
        cred.refresh_claim_deadline_unix = now + REFRESH_CLAIM_TTL_MS
        return claim


@_sealing
def finalize_refresh(connector_pk: int, *, claim: str, identity_generation: int,
                     credential_revision: int, token: dict) -> bool:
    """Atomically store refreshed (possibly rotated) tokens; False discards a
    late result that no longer matches the claim/identity/revision."""
    with get_db() as session:
        row = repo.get_connector_by_pk(session, connector_pk, lock=True)
        cred = repo.get_credential(session, connector_pk, "oauth_token", lock=True)
        if row is None or row.deleted_at_unix is not None or cred is None \
                or row.identity_generation != identity_generation \
                or cred.identity_generation != identity_generation \
                or cred.credential_revision != credential_revision \
                or cred.refresh_claim != claim or cred.status != "usable":
            return False
        current = _open_credential(session, row, cred)
        merged = dict(current)
        merged["access_token"] = token["access_token"]
        merged["token_type"] = token.get("token_type") or current.get("token_type")
        if token.get("refresh_token"):
            merged["refresh_token"] = token["refresh_token"]
        merged["expires_at_unix"] = token.get("expires_at_unix")
        meta = _json_dict(cred.public_meta)
        if token.get("scope"):
            meta["scope"] = token["scope"]
        envelope = crypto.seal(merged, _context(session, row, "oauth_token"))
        crypto.store_envelope(cred, envelope)
        cred.public_meta = json.dumps(meta)
        cred.access_expires_at_unix = token.get("expires_at_unix")
        cred.credential_revision += 1
        cred.refresh_claim = None
        cred.refresh_claim_deadline_unix = None
        return True


def fail_refresh(connector_pk: int, *, claim: str, identity_generation: int,
                 reconnect: bool) -> None:
    """Release the claim; `reconnect` (invalid grant or uncertain outcome)
    marks the credential unusable until the owner reconnects."""
    with get_db() as session:
        row = repo.get_connector_by_pk(session, connector_pk, lock=True)
        cred = repo.get_credential(session, connector_pk, "oauth_token", lock=True)
        if row is None or cred is None or cred.refresh_claim != claim \
                or cred.identity_generation != identity_generation:
            return
        cred.refresh_claim = None
        cred.refresh_claim_deadline_unix = None
        if reconnect:
            cred.status = "reconnect_required"
            row.auth_state = "reconnect_required"


# ---------------------------------------------------------------------------
# Launch snapshots and grants
# ---------------------------------------------------------------------------

def grant_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_launch(user_id: int, chat_id: str, run_seq: Optional[int] = None) -> tuple[dict, str]:
    """Snapshot the owner's launchable connectors for one actual process launch.

    Returns (sanitized summary, plaintext grant). Only the grant digest is
    stored; the caller stages the grant in protected per-launch material.
    """
    now = _now()
    token = secrets.token_urlsafe(32)
    with get_db() as session:
        launch = McpLaunchEntity(
            launch_id=str(uuid.uuid4()), user_id=user_id, chat_id=chat_id, run_seq=run_seq,
            token_hash=grant_digest(token), expires_at_unix=now + LAUNCH_IDLE_TTL_MS,
            status="active",
        )
        session.add(launch)
        session.flush()
        included, skipped = [], []
        for row in repo.list_live_connectors(session, user_id):
            if not row.desired_enabled:
                continue
            blocking = _blocking(session, row)
            if blocking:
                skipped.append({"connector_id": row.connector_id, "name": row.name,
                                "reason": blocking[0]})
                continue
            if len(included) >= MAX_CONNECTORS_PER_LAUNCH:
                skipped.append({"connector_id": row.connector_id, "name": row.name,
                                "reason": "launch_connector_limit"})
                continue
            approved = _json_list(row.approved_tools)
            snapshot = [tool for tool in _json_list(row.catalog) if tool["name"] in approved]
            session.add(McpLaunchConnectorEntity(
                launch_pk=launch.id, connector_pk=row.id, config_revision=row.config_revision,
                identity_generation=row.identity_generation, endpoint=row.endpoint,
                approved_tools=json.dumps(approved), tool_snapshot=json.dumps(snapshot),
                status="pending",
            ))
            included.append({"connector_id": row.connector_id, "name": row.name,
                             "config_revision": row.config_revision,
                             "identity_generation": row.identity_generation, "tools": approved})
        session.flush()
        return ({"launch_id": launch.launch_id, "chat_id": chat_id, "run_seq": run_seq,
                 "expires_at_unix": launch.expires_at_unix, "connectors": included,
                 "skipped": skipped}, token)


@dataclass(frozen=True)
class LaunchGrant:
    launch_id: str
    user_id: int
    connector_pk: int
    connector_id: str
    identity_generation: int
    endpoint: str
    preset: Optional[str]
    auth_mode: str
    approved_tools: tuple
    tool_snapshot: tuple


def _verify_launch(session, launch_id: Any, token: Any, now: int, *, lock: bool = False
                   ) -> McpLaunchEntity:
    if not isinstance(launch_id, str) or not isinstance(token, str) or not token:
        raise McpError("forbidden", "launch grant is invalid")
    launch = repo.get_launch(session, launch_id, lock=lock)
    if launch is None or not hmac.compare_digest(launch.token_hash, grant_digest(token)):
        raise McpError("forbidden", "launch grant is invalid")
    if launch.status != "active" or launch.ended_at_unix is not None or launch.expires_at_unix <= now:
        raise McpError("forbidden", "launch grant expired or ended")
    return launch


def authorize_launch_call(launch_id: str, token: str, connector_id: str) -> LaunchGrant:
    """Resolve a gateway request to its pinned snapshot, denying replaced,
    disconnected or deleted identities even though disable/approval edits
    never mutate the snapshot."""
    now = _now()
    with get_db() as session:
        launch = _verify_launch(session, launch_id, token, now)
        for snap in repo.launch_connectors(session, launch.id):
            row = repo.get_connector_by_pk(session, snap.connector_pk)
            if row is None or row.connector_id != connector_id:
                continue
            if snap.status == "excluded":
                # Left out of the staged config (startup probe failed or timed
                # out): the grant never gains that connector later.
                raise McpError("forbidden", "connector is not part of this launch")
            if row.deleted_at_unix is not None or row.identity_generation != snap.identity_generation:
                raise McpError("not_connected", "connector authorization was replaced or removed")
            return LaunchGrant(launch.launch_id, launch.user_id, row.id, row.connector_id,
                               snap.identity_generation, snap.endpoint, row.preset, row.auth_mode,
                               tuple(_json_list(snap.approved_tools)),
                               tuple(_json_list(snap.tool_snapshot)))
        raise McpError("forbidden", "connector is not part of this launch")


class LaunchSession:
    """Decrypted upstream session state for one launch connector. Sealing
    happens only when the state changed; `checkpoint()` seals early so a
    side-effecting call never runs before its session can be stored."""

    def __init__(self, context: dict, stored: Optional[str]):
        self._context = context
        self.stored = stored
        try:
            self.state = (crypto.open_envelope(crypto.Envelope(**json.loads(stored)), context)
                          if stored else {})
        except (crypto.McpKeyUnavailable, crypto.McpCiphertextInvalid):
            raise McpError("key_unavailable", "connector encryption key is unavailable") from None
        self._saved = dict(self.state)

    def checkpoint(self) -> None:
        if self.state == self._saved:
            return
        try:
            self.stored = json.dumps(asdict(crypto.seal(self.state, self._context)))
        except (crypto.McpKeyUnavailable, crypto.McpCiphertextInvalid):
            raise McpError("key_unavailable", "connector encryption key is unavailable") from None
        self._saved = dict(self.state)


@contextmanager
def launch_session(launch_id: str, token: str, connector_id: str):
    """Serialize one connector's upstream session across API instances.

    Only the snapshot row is locked during the bounded operation, with a
    bounded lock wait. Disconnect and stop do not wait on this lock. Session
    material is encrypted and bound to this launch, never returned in
    management projections.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    with get_db() as session:
        try:
            session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            launch = _verify_launch(session, launch_id, token, _now())
            snap = (session.query(McpLaunchConnectorEntity)
                    .join(McpConnectorEntity, McpConnectorEntity.id == McpLaunchConnectorEntity.connector_pk)
                    .filter(McpLaunchConnectorEntity.launch_pk == launch.id,
                            McpConnectorEntity.connector_id == connector_id)
                    .with_for_update(of=McpLaunchConnectorEntity).one_or_none())
        except OperationalError:
            err = McpError("provider_unavailable", "connector is busy; retry")
            err.busy = True
            raise err from None
        if snap is None or snap.status == "excluded":
            raise McpError("forbidden", "connector is not part of this launch")
        slot = LaunchSession(crypto.crypto_context(repo.public_user_id(session, launch.user_id),
                                                   connector_id, snap.identity_generation,
                                                   f"runtime:{launch_id}"),
                             snap.upstream_session_id)
        yield slot
        slot.checkpoint()
        snap.upstream_session_id = slot.stored


def end_chat_launches(user_id: int, chat_id: str) -> None:
    """A replacement process invalidates all prior grants, not just the latest."""
    with get_db() as session:
        (session.query(McpLaunchEntity)
         .filter(McpLaunchEntity.user_id == user_id, McpLaunchEntity.chat_id == chat_id,
                 McpLaunchEntity.status == "active")
         .update({"status": "ended", "ended_at_unix": _now()}, synchronize_session=False))


def renew_launch(launch_id: str, token: str) -> int:
    now = _now()
    with get_db() as session:
        launch = _verify_launch(session, launch_id, token, now, lock=True)
        launch.expires_at_unix = now + LAUNCH_IDLE_TTL_MS
        return launch.expires_at_unix


def end_launch(launch_id: str, *, status: str = "ended") -> None:
    now = _now()
    with get_db() as session:
        launch = repo.get_launch(session, launch_id, lock=True)
        if launch is not None and launch.status == "active":
            launch.status = "ended" if status != "expired" else "expired"
            launch.ended_at_unix = now


def record_launch_connector_status(launch_id: str, connector_id: str, *, status: str,
                                   error_code: Optional[str] = None) -> None:
    """Best-effort applied status; never waits long on a busy snapshot row."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    try:
        with get_db() as session:
            session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            _set_launch_connector_status(session, launch_id, connector_id, status, error_code)
    except OperationalError:
        pass


def exclude_launch_connector(launch_id: str, connector_id: str, *, error_code: str) -> None:
    """Terminally drop a connector from a launch's authority. Waits out any
    in-flight gateway operation (each is bounded well below this lock wait);
    raises if it cannot be recorded so the caller fails closed."""
    from sqlalchemy import text

    with get_db() as session:
        session.execute(text("SET LOCAL lock_timeout = '12s'"))
        _set_launch_connector_status(session, launch_id, connector_id, "excluded", error_code)


def _set_launch_connector_status(session, launch_id, connector_id, status, error_code) -> None:
    launch = repo.get_launch(session, launch_id)
    if launch is None:
        return
    for snap in repo.launch_connectors(session, launch.id):
        row = repo.get_connector_by_pk(session, snap.connector_pk)
        if row is not None and row.connector_id == connector_id:
            if snap.status == "excluded":
                return  # terminal: a late in-flight result cannot revive it
            snap.status = status[:32]
            snap.error_code = error_code if error_code in McpError.STATUS else None
            return


def launch_status(user_id: int, chat_id: Optional[str] = None) -> dict[str, Any]:
    """Desired state versus the latest launch's applied snapshot (sanitized)."""
    with get_db() as session:
        connectors = repo.list_live_connectors(session, user_id)
        desired = [{"connector_id": row.connector_id, "name": row.name,
                    "desired_enabled": bool(row.desired_enabled),
                    "config_revision": row.config_revision,
                    "identity_generation": row.identity_generation} for row in connectors]
        launch = repo.latest_launch_for_chat(session, user_id, chat_id) if chat_id else None
        applied = None
        if launch is not None:
            items = []
            for snap in repo.launch_connectors(session, launch.id):
                row = repo.get_connector_by_pk(session, snap.connector_pk)
                items.append({"connector_id": row.connector_id if row else None,
                              "config_revision": snap.config_revision,
                              "identity_generation": snap.identity_generation,
                              "tools": _json_list(snap.approved_tools),
                              "status": snap.status, "error_code": snap.error_code})
            applied = {"launch_id": launch.launch_id, "chat_id": launch.chat_id,
                       "run_seq": launch.run_seq, "status": launch.status,
                       "created_at": launch.created_at, "connectors": items}
        return {"desired": desired, "applied": applied}


def cleanup_expired_state(now: Optional[int] = None) -> dict[str, int]:
    """Bounded retention: expire idle launches, drop old launch history and
    old terminal OAuth transactions."""
    now = now if now is not None else _now()
    with get_db() as session:
        expired = (session.query(McpLaunchEntity)
                   .filter(McpLaunchEntity.status == "active",
                           McpLaunchEntity.expires_at_unix <= now)
                   .update({"status": "expired", "ended_at_unix": now}, synchronize_session=False))
        dropped = (session.query(McpLaunchEntity)
                   .filter(McpLaunchEntity.status != "active",
                           McpLaunchEntity.ended_at_unix <= now - LAUNCH_RETENTION_MS)
                   .delete(synchronize_session=False))
        stale_tx = (session.query(McpOAuthTransactionEntity)
                    .filter(McpOAuthTransactionEntity.expires_at_unix <= now - TRANSACTION_RETENTION_MS)
                    .delete(synchronize_session=False))
        return {"launches_expired": expired, "launches_deleted": dropped,
                "transactions_deleted": stale_tx}


@_sealing
def rewrap_credentials(target_key_id: str, *, limit: int = 100) -> dict[str, int]:
    """Explicit bounded rotation step: re-seal credentials not yet under the
    currently configured key. Each rewrapped record is read back before the
    next; old-key decrypt permission must stay until this reports zero left."""
    rewrapped = 0
    with get_db() as session:
        rows = (session.query(McpCredentialEntity)
                .filter(McpCredentialEntity.key_id != target_key_id)
                .order_by(McpCredentialEntity.id).limit(max(1, min(limit, 1000)))
                .with_for_update().all())
        for cred in rows:
            row = repo.get_connector_by_pk(session, cred.connector_pk)
            context = crypto.crypto_context(repo.public_user_id(session, row.user_id),
                                            row.connector_id, cred.identity_generation, cred.kind)
            try:
                plain = crypto.open_envelope(crypto.envelope_of(cred), context)
            except (crypto.McpKeyUnavailable, crypto.McpCiphertextInvalid):
                raise McpError("key_unavailable", "an existing credential cannot be decrypted") from None
            envelope = crypto.seal(plain, context)
            if crypto.open_envelope(envelope, context) != plain:
                raise McpError("key_unavailable", "rewrap verification failed")
            crypto.store_envelope(cred, envelope)
            rewrapped += 1
        remaining = (session.query(McpCredentialEntity.id)
                     .filter(McpCredentialEntity.key_id != target_key_id).count()) - rewrapped
        return {"rewrapped": rewrapped, "remaining": max(0, remaining)}
