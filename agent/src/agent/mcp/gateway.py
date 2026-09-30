"""Launch-scoped, tools-only boundary. No caller-controlled upstream transport."""

import base64
import json
from urllib.parse import quote

from agent.mcp import manager
from agent.mcp.client import McpHttpClient, SUPPORTED_PROTOCOL_VERSIONS
from agent.mcp.egress import OPERATION_TIMEOUT_S, TOOL_CALL_TIMEOUT_S, deadline
from storage.service import mcp as svc

MAX_REQUEST_BYTES = 1024 * 1024
# The relayed tools-only subset (initialize/ping/tools list+call) is unchanged
# across these revisions, so upstream results stay valid for each of them.
DOWNSTREAM_PROTOCOL_VERSIONS = ("2025-11-25", *SUPPORTED_PROTOCOL_VERSIONS)
METHOD_PARAMS = {
    "initialize": {"protocolVersion", "capabilities", "clientInfo"},
    "notifications/initialized": set(), "ping": set(), "tools/list": set(),
    "tools/call": {"name", "arguments"},
}


def validate_request(body):
    if not isinstance(body, dict) or set(body) != {"connector_id", "method", "params"}:
        raise svc.McpError("invalid_input", "invalid runtime envelope")
    method, params = body["method"], body["params"]
    if not isinstance(method, str) or method not in METHOD_PARAMS:
        raise svc.McpError("forbidden", "MCP method is not available")
    # `_meta` is the protocol's per-request envelope (e.g. progressToken); it
    # is accepted but never forwarded upstream.
    if (not isinstance(body["connector_id"], str) or not isinstance(params, dict)
            or set(params) - METHOD_PARAMS[method] - {"_meta"}
            or not isinstance(params.get("_meta", {}), dict)):
        raise svc.McpError("invalid_input", "invalid MCP parameters")
    if method == "tools/call" and (not isinstance(params.get("name"), str)
                                    or not isinstance(params.get("arguments", {}), dict)):
        raise svc.McpError("invalid_input", "invalid tool call")
    if len(json.dumps(body).encode()) > MAX_REQUEST_BYTES:
        raise svc.McpError("invalid_input", "runtime request is too large")
    return method, params


def echo_forms(secrets):
    """Known secrets plus their common transport encodings, longest first."""
    forms = set()
    for secret in secrets:
        if not secret:
            continue
        forms.add(secret)
        if len(secret) >= 8:  # encoded forms of tiny values would mangle ordinary text
            raw = secret.encode()
            forms.update({quote(secret, safe=""), base64.b64encode(raw).decode(),
                          base64.urlsafe_b64encode(raw).decode().rstrip("=")})
    return sorted(forms, key=len, reverse=True)


def redact(value, secrets):
    """Remove known credential echoes without interpreting provider text."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {redact(key, secrets): redact(item, secrets) for key, item in value.items()}
    return value


def dispatch(launch_id, token, body, *, egress=None):
    method, params = validate_request(body)
    cid = body["connector_id"]
    grant = svc.authorize_launch_call(launch_id, token, cid)
    excluded = svc.PRESETS.get(grant.preset, {}).get("excluded_tools", ())
    approved = set(grant.approved_tools) - set(excluded)
    if method == "tools/call" and params["name"] not in approved:
        raise svc.McpError("forbidden", "tool is not approved for this launch")
    if method == "ping":
        svc.renew_launch(launch_id, token)
        return {}
    if method == "notifications/initialized":
        return {}
    if method == "initialize":
        # Local (adapter-facing) negotiation, independent of the upstream
        # session: echo a supported request, otherwise counter-offer our
        # newest and let the client decide (MCP lifecycle rule).
        requested = params.get("protocolVersion")
        version = requested if requested in DOWNSTREAM_PROTOCOL_VERSIONS else DOWNSTREAM_PROTOCOL_VERSIONS[0]
        return {"protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "y-agent-connector", "version": "1"}}
    if not approved:
        return {"tools": []}
    egress = egress or manager.default_egress()
    failure = None
    try:
        # One wall-clock budget covers refresh, (re)initialize, listing and the call.
        with deadline(TOOL_CALL_TIMEOUT_S if method == "tools/call" else OPERATION_TIMEOUT_S), \
                svc.launch_session(launch_id, token, cid) as session:
            state, client = session.state, None
            try:
                # Recheck after waiting for the cross-instance session lock.
                svc.authorize_launch_call(launch_id, token, cid)
                headers = manager.auth_headers(grant.connector_pk, grant.identity_generation, egress=egress)
                client = McpHttpClient(grant.endpoint, headers, egress,
                                       session_id=state.get("session_id"),
                                       protocol_version=state.get("protocol_version"))
                client.capabilities = state.get("capabilities", {})
                tools = svc.normalize_tools(client.list_tools(), preset=grant.preset)
                available = {tool["name"] for tool in tools}
                if method == "tools/call":
                    if params["name"] not in available:
                        raise svc.McpError("provider_unavailable", "approved tool is no longer available")
                    svc.authorize_launch_call(launch_id, token, cid)
                    # Seal a newly initialized session before the side effect,
                    # so a key failure can never follow an executed call.
                    session.state = _session_state(client)
                    session.checkpoint()
                    result = client.call_tool(params["name"], params.get("arguments", {}))
                    if not isinstance(result.get("content"), list):
                        raise svc.McpError("protocol_error", "provider returned an invalid tool result")
                else:
                    # Schemas/descriptions are frozen at approval; availability is live.
                    result = {"tools": [tool for tool in grant.tool_snapshot
                                        if tool["name"] in approved & available]}
                secrets = [token, client.session_id or "", *headers.values()]
                secrets += [v[7:] for v in headers.values() if v.startswith("Bearer ")]
                result = redact(result, echo_forms(secrets))
            except svc.McpError as err:
                failure = err
            if client is not None:
                # Persist even on failure: a lost session is cleared for the next safe operation.
                session.state = _session_state(client)
        if failure is not None:
            raise failure
        svc.record_launch_connector_status(launch_id, cid, status="available")
        return result
    except svc.McpError as err:
        if not getattr(err, "busy", False):  # concurrency is not connector health
            svc.record_launch_connector_status(launch_id, cid, status="unavailable", error_code=err.code)
        raise


def _session_state(client):
    return {"session_id": client.session_id, "protocol_version": client.protocol_version,
            "capabilities": client.capabilities}
