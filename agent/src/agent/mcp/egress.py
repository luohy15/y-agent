"""Public-only HTTPS egress shared by MCP discovery, OAuth and tool traffic.

Every outbound dial resolves the hostname once, rejects the connection if any
resolved address is not globally routable (loopback, private, link-local and
cloud metadata, CGNAT, multicast, reserved, IPv4-mapped/embedding IPv6), and
connects to that validated address. TLS still verifies the certificate and
SNI against the original hostname, so pinning never weakens HTTPS. There is no
second resolver between check and connect, and each new connection (including
one after a redirect) is checked again.

Environment proxies are ignored (`trust_env=False`), redirects are never
followed implicitly, and response bodies are capped.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Optional
from urllib.parse import urljoin

import httpcore
import httpx

from storage.service.mcp import McpError, validate_https_url

CONNECT_TIMEOUT_S = 3.0
OPERATION_TIMEOUT_S = 10.0
TOOL_CALL_TIMEOUT_S = 30.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_METADATA_REDIRECTS = 3
USER_AGENT = "y-agent-mcp/1.0"

_EMBEDDING_V6_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "2002::/16",       # 6to4
    "2001::/32",       # Teredo
    "64:ff9b::/96",    # NAT64 well-known
    "64:ff9b:1::/48",  # NAT64 local-use
    "::/96",           # IPv4-compatible (deprecated)
))

Resolver = Callable[[str, int], list]


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if any(ip in net for net in _EMBEDDING_V6_NETWORKS):
            return False
    return bool(ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
                                      or ip.is_multicast or ip.is_reserved
                                      or ip.is_unspecified))


def system_resolver(host: str, port: int) -> list:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list = []
    for info in infos:
        address = info[4][0]
        if address not in seen:
            seen.append(address)
    return seen


def resolve_public(host: str, port: int, resolver: Resolver) -> str:
    """Resolve once; every answer must be public, then pin the first."""
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addresses = [host]
    except ValueError:
        try:
            addresses = list(resolver(host, port))
        except (OSError, UnicodeError):
            raise McpError("provider_unavailable", "provider host could not be resolved") from None
    if not addresses:
        raise McpError("provider_unavailable", "provider host could not be resolved")
    if not all(isinstance(a, str) and is_public_address(a) for a in addresses):
        raise McpError("network_blocked", "provider host resolves to a non-public address")
    return addresses[0]


class PinnedBackend(httpcore.NetworkBackend):
    """httpcore backend that validates and pins the dial address itself."""

    def __init__(self, resolver: Resolver, inner: Optional[httpcore.NetworkBackend] = None):
        self._resolver = resolver
        self._inner = inner or httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        address = resolve_public(host, port, self._resolver)
        return self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                       socket_options=socket_options)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise McpError("network_blocked", "unix sockets are not permitted")

    def sleep(self, seconds):
        self._inner.sleep(seconds)


class PinnedTransport(httpx.HTTPTransport):
    """`httpx.HTTPTransport` whose pool dials only through `PinnedBackend`."""

    def __init__(self, resolver: Resolver, inner: Optional[httpcore.NetworkBackend] = None,
                 ssl_context=None):
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context or httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=5.0,
            retries=0,
            network_backend=PinnedBackend(resolver, inner),
        )


@dataclass
class Response:
    status: int
    headers: httpx.Headers
    body: bytes
    url: str

    def json(self):
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, ValueError):
            raise McpError("protocol_error", "provider returned malformed JSON") from None


def _mapped(err: Exception) -> McpError:
    """Closed error; `uncertain` marks failures after the request may have
    reached the provider (never replay those automatically)."""
    if isinstance(err, McpError):
        return err
    if isinstance(err, (httpx.ConnectTimeout, httpx.PoolTimeout)):
        out = McpError("timeout", "provider connection timed out")
        out.uncertain = False
    elif isinstance(err, httpx.TimeoutException):
        out = McpError("timeout", "provider request timed out")
        out.uncertain = True
    elif isinstance(err, httpx.ConnectError):
        out = McpError("provider_unavailable", "provider connection failed")
        out.uncertain = False
    else:
        out = McpError("provider_unavailable", "provider connection failed")
        out.uncertain = True
    return out


class Egress:
    """One configured outbound policy. Tests inject a resolver/backend (dial
    spies) or a whole transport (fake providers)."""

    def __init__(self, *, resolver: Optional[Resolver] = None,
                 backend: Optional[httpcore.NetworkBackend] = None,
                 transport: Optional[httpx.BaseTransport] = None,
                 max_response_bytes: int = MAX_RESPONSE_BYTES):
        self._transport = transport or PinnedTransport(resolver or system_resolver, backend)
        self.max_response_bytes = max_response_bytes

    @contextmanager
    def stream(self, method: str, url: str, *, headers: Optional[dict] = None,
               content: Optional[bytes] = None, data: Optional[dict] = None,
               timeout: float = OPERATION_TIMEOUT_S, allow_query: bool = True
               ) -> Iterator[httpx.Response]:
        validate_https_url(url, allow_query=allow_query)
        request_headers = {"User-Agent": USER_AGENT}
        request_headers.update(headers or {})
        client = httpx.Client(transport=self._transport, trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT_S, timeout)))
        try:
            with client.stream(method, url, headers=request_headers, content=content,
                               data=data) as response:
                yield response
        except McpError:
            raise
        except httpx.HTTPError as err:
            raise _mapped(err) from None
        except OSError as err:
            raise _mapped(err) from None

    def read_capped(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
            raise McpError("response_too_large", "provider response is too large")
        body = bytearray()
        try:
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise McpError("response_too_large", "provider response is too large")
        except httpx.HTTPError as err:
            raise _mapped(err) from None
        return bytes(body)

    def request(self, method: str, url: str, **kwargs) -> Response:
        with self.stream(method, url, **kwargs) as response:
            body = self.read_capped(response)
            return Response(response.status_code, response.headers, body, url)

    def get_metadata(self, url: str, *, timeout: float = OPERATION_TIMEOUT_S) -> Response:
        """Credential-free metadata GET following at most three redirects,
        each hop revalidated (syntax here, address at dial)."""
        current = url
        for _ in range(MAX_METADATA_REDIRECTS + 1):
            response = self.request("GET", current, headers={"Accept": "application/json"},
                                    timeout=timeout)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise McpError("protocol_error", "provider redirect has no location")
                current = validate_https_url(urljoin(current, location), allow_query=True)
                continue
            return response
        raise McpError("protocol_error", "provider metadata redirected too many times")
