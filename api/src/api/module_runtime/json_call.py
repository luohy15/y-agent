"""In-process ASGI adapter for owner-bound module JSON calls (todo 3838).

Reuses the active-version dispatcher: the same maintainer gate, dispatch
scope, and load errors. Not an HTTP self-call and not an import of another
module's tables. Request/response policy lives in `agent.module_json`; this
adapter counts response bytes in `send` and aborts before storing excess.
A context depth stops a module from calling this until the stack unwinds.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Optional

from agent.module_json import (
    JSON_MAX_BYTES,
    JSON_MAX_DEPTH,
    JSON_TIMEOUT_SECONDS,
    ModuleJsonError,
    check_declared_length,
    check_media_type,
    check_status,
    decode_object,
    validate_request,
)

__all__ = ["JSON_MAX_BYTES", "ModuleJsonError", "call_published_module"]

_depth: ContextVar[int] = ContextVar("module_json_depth", default=0)


def _scope(user_id: int, slug: str, method: str, path: str, payload: bytes) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": f"/api/module/{slug}{path}",
        "raw_path": f"/api/module/{slug}{path}".encode("utf-8"),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode("ascii"))],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 0),
        "state": {"user_id": user_id},
    }


def _header(headers, name: str) -> Optional[str]:
    target = name.lower().encode("ascii")
    for key, value in headers:
        if key.lower() == target:
            return value.decode("latin1")
    return None


class _Collector:
    """Bounded ASGI `send`: refuses a declared or streamed body over the cap."""

    def __init__(self):
        self.status = 500
        self.headers = []
        self.chunks = []
        self.received = 0
        self.error: Optional[ModuleJsonError] = None

    async def send(self, message):
        if self.error is not None:
            raise self.error
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = message.get("headers") or []
            try:
                check_declared_length(_header(self.headers, "content-length"))
            except ModuleJsonError as exc:
                self.error = exc
                raise
        elif message["type"] == "http.response.body":
            chunk = message.get("body") or b""
            if self.received + len(chunk) > JSON_MAX_BYTES:
                self.error = ModuleJsonError("size", "module JSON response exceeds the size limit")
                raise self.error
            self.received += len(chunk)
            self.chunks.append(chunk)


async def _invoke(dispatcher, scope: dict, payload: bytes) -> _Collector:
    collector = _Collector()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    try:
        await dispatcher(scope, receive, collector.send)
    except ModuleJsonError:
        raise
    except Exception as exc:
        if collector.error is not None:
            raise collector.error from exc
        raise ModuleJsonError("upstream", "module JSON call failed") from exc
    if collector.error is not None:
        # The app swallowed our refusal; it still stands.
        raise collector.error
    return collector


async def call_published_module(
    user_id: int,
    slug: str,
    method: str,
    path: str,
    body: Optional[dict] = None,
    *,
    timeout: float = JSON_TIMEOUT_SECONDS,
    dispatcher=None,
) -> dict:
    payload = validate_request(user_id, method, path, body, timeout)
    depth = _depth.get()
    if depth >= JSON_MAX_DEPTH:
        raise ModuleJsonError("recursion", "module JSON call depth exceeded")
    if dispatcher is None:
        from api.module_runtime.dispatcher import module_dispatcher
        dispatcher = module_dispatcher
    token = _depth.set(depth + 1)
    try:
        try:
            collector = await asyncio.wait_for(
                _invoke(dispatcher, _scope(user_id, slug, method, path, payload), payload),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ModuleJsonError("timeout", "module JSON call timed out") from exc
    finally:
        _depth.reset(token)
    check_status(collector.status)
    check_media_type(_header(collector.headers, "content-type") or "", collector.status)
    return decode_object(b"".join(collector.chunks), collector.status)
