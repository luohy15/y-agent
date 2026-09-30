"""Tools-only MCP Streamable HTTP client over the public-egress policy.

Implements exactly the subset the connector boundary allows: initialize,
notifications/initialized, ping, paginated tools/list and tools/call, with JSON
or SSE responses. Server-initiated requests (sampling, elicitation, roots) are
never answered, resources/prompts are never requested, and a request is never
replayed after an uncertain failure. Authenticated requests never follow
redirects, so credentials only reach the validated endpoint origin.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional

import httpx

from storage.service.mcp import MAX_TOOLS, McpError
from agent.mcp.egress import OPERATION_TIMEOUT_S, TOOL_CALL_TIMEOUT_S, Egress

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
MAX_PAGES = 100
MAX_CURSOR = 1024
MAX_SESSION_ID = 256


def _session_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not value or len(value) > MAX_SESSION_ID or any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise McpError("protocol_error", "provider returned an invalid session id")
    return value


def iter_sse_messages(lines: Iterator[str], max_bytes: int) -> Iterator[Any]:
    """Yield decoded JSON `data` payloads from an SSE stream, bounded."""
    data: list[str] = []
    total = 0
    for line in lines:
        total += len(line) + 1
        if total > max_bytes:
            raise McpError("response_too_large", "provider response is too large")
        if line == "":
            if data:
                payload = "\n".join(data)
                data = []
                try:
                    yield json.loads(payload)
                except ValueError:
                    raise McpError("protocol_error", "provider sent a malformed event") from None
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        try:
            yield json.loads("\n".join(data))
        except ValueError:
            raise McpError("protocol_error", "provider sent a malformed event") from None


class McpHttpClient:
    def __init__(self, endpoint: str, auth_headers: dict, egress: Egress, *,
                 session_id: Optional[str] = None, protocol_version: Optional[str] = None):
        self.endpoint = endpoint
        self._auth = dict(auth_headers)
        self._egress = egress
        self.session_id = session_id
        self.protocol_version = protocol_version
        self.capabilities: dict = {}
        self._next_id = 1

    def _headers(self) -> dict:
        headers = {"Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json"}
        headers.update(self._auth)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if 300 <= status < 400:
            raise McpError("protocol_error", "provider redirected an authenticated request")
        if status in (401, 403):
            raise McpError("auth_failed", "provider rejected the connector credentials")
        if status == 404:
            raise McpError("provider_unavailable", "provider session or endpoint not found")
        if status == 429 or status >= 500:
            raise McpError("provider_unavailable", "provider is temporarily unavailable")
        if status >= 400:
            raise McpError("provider_error", "provider rejected the request")

    def _send(self, message: dict, *, timeout: float, capture_session: bool = False) -> Optional[dict]:
        expect = "id" in message
        with self._egress.stream("POST", self.endpoint, headers=self._headers(), allow_query=False,
                                 content=json.dumps(message).encode(), timeout=timeout) as response:
            self._check_status(response)
            if capture_session:
                self.session_id = _session_id(response.headers.get("mcp-session-id"))
            if not expect:
                return None
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype == "application/json":
                try:
                    payload = json.loads(self._egress.read_capped(response))
                except ValueError:
                    raise McpError("protocol_error", "provider returned malformed JSON") from None
                return self._match(payload, message["id"])
            if ctype == "text/event-stream":
                try:
                    for payload in iter_sse_messages(response.iter_lines(), self._egress.max_response_bytes):
                        matched = self._match(payload, message["id"], allow_other=True)
                        if matched is not None:
                            return matched
                except httpx.HTTPError:
                    err = McpError("provider_unavailable", "provider stream failed")
                    err.uncertain = True
                    raise err from None
                err = McpError("protocol_error", "provider stream ended without a response")
                err.uncertain = True
                raise err
            raise McpError("protocol_error", "provider returned an unsupported content type")

    @staticmethod
    def _match(payload: Any, request_id: int, *, allow_other: bool = False) -> Optional[dict]:
        if isinstance(payload, list):
            raise McpError("protocol_error", "JSON-RPC batches are not supported")
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise McpError("protocol_error", "provider returned malformed JSON-RPC")
        if "method" in payload:
            # Server notification or server-initiated request (sampling,
            # elicitation, roots): never answered, never forwarded.
            if allow_other:
                return None
            raise McpError("protocol_error", "provider sent an unexpected request")
        if payload.get("id") != request_id:
            if allow_other:
                return None
            raise McpError("protocol_error", "provider response id does not match")
        if "error" in payload:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            code = error.get("code") if isinstance(error.get("code"), int) else None
            err = McpError("provider_error", f"provider returned MCP error {code}")
            err.rpc_code = code
            raise err
        result = payload.get("result")
        if not isinstance(result, dict):
            raise McpError("protocol_error", "provider returned a malformed result")
        return result

    def _request(self, method: str, params: Optional[dict], *, timeout: float = OPERATION_TIMEOUT_S,
                 capture_session: bool = False) -> dict:
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self._send(message, timeout=timeout, capture_session=capture_session)

    def initialize(self) -> dict:
        self.session_id = None
        self.protocol_version = None
        result = self._request("initialize", {
            "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[0], "capabilities": {},
            "clientInfo": {"name": "y-agent", "version": "1.0"}}, capture_session=True)
        version = result.get("protocolVersion")
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise McpError("protocol_error", "provider negotiated an unsupported protocol version")
        self.protocol_version = version
        self.capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=OPERATION_TIMEOUT_S)
        return result

    def ping(self) -> None:
        self._request("ping", None)

    def list_tools(self) -> list[dict]:
        if self.protocol_version is None:
            self.initialize()
        if "tools" not in self.capabilities:
            return []
        tools: list = []
        cursor: Optional[str] = None
        seen: set = set()
        for _ in range(MAX_PAGES):
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise McpError("protocol_error", "provider returned a malformed tool list")
            tools.extend(page)
            if len(tools) > MAX_TOOLS:
                raise McpError("response_too_large", f"provider returned more than {MAX_TOOLS} tools")
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
            if not isinstance(cursor, str) or len(cursor) > MAX_CURSOR or cursor in seen:
                raise McpError("protocol_error", "provider returned an invalid pagination cursor")
            seen.add(cursor)
        raise McpError("response_too_large", "provider tool list has too many pages")

    def call_tool(self, name: str, arguments: dict, *, timeout: float = TOOL_CALL_TIMEOUT_S) -> dict:
        """One attempt only: a failed call is reported, never replayed."""
        if self.protocol_version is None:
            self.initialize()
        return self._request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)

    def close(self) -> None:
        if not self.session_id:
            return
        try:
            with self._egress.stream("DELETE", self.endpoint, headers=self._headers(),
                                     allow_query=False, timeout=OPERATION_TIMEOUT_S):
                pass
        except McpError:
            pass
        self.session_id = None
