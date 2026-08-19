"""Privacy-safe timing at the outer ASGI request boundary."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Callable, Iterable

from loguru import logger
from starlette.routing import Match

from storage.service import api_latency as latency_service


MONITOR_SCOPE_KEY = "y_monitor"
UNMATCHED_ROUTE = "<unmatched>"
MAX_ROUTE_LENGTH = 512
ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
ALLOWED_STATUS_CLASSES = frozenset({"2xx", "3xx", "4xx", "5xx", "unk"})
ALLOWED_COMPLETIONS = frozenset(
    {"normal", "disconnect", "cancelled", "internal_failure"}
)
EXCLUDED_OPERATIONAL_PATHS = frozenset({
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})
# Long-lived server-push streams measure session lifetime, not API latency.
EXCLUDED_STREAMING_PATHS = frozenset({"/api/chat/messages"})
EXCLUDED_PATHS = EXCLUDED_OPERATIONAL_PATHS | EXCLUDED_STREAMING_PATHS
_FALSE_VALUES = frozenset({"0", "false", "off", "no"})


def normalize_method(value: object) -> str:
    method = str(value or "").upper()
    return method if method in ALLOWED_METHODS else "OTHER"


def normalize_status_class(value: object) -> str:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return "unk"
    status_class = f"{status // 100}xx"
    return status_class if status_class in ALLOWED_STATUS_CLASSES else "unk"


def normalize_completion(value: object) -> str:
    completion = str(value or "")
    return completion if completion in ALLOWED_COMPLETIONS else "internal_failure"


def should_capture(scope: dict) -> bool:
    if os.getenv("Y_AGENT_MONITOR_CAPTURE", "1").lower() in _FALSE_VALUES:
        return False
    if scope.get("type") != "http" or str(scope.get("method") or "").upper() == "OPTIONS":
        return False
    path = scope.get("path") or ""
    root_path = scope.get("root_path") or ""
    full_path = root_path + path if root_path and not path.startswith(root_path) else path
    return full_path.startswith("/api/") and full_path not in EXCLUDED_PATHS


def _bounded_route(value: str) -> str:
    return value if len(value) <= MAX_ROUTE_LENGTH else UNMATCHED_ROUTE


def matched_route_template(scope: dict, routes: Iterable) -> str:
    """Return only a bounded framework-owned template, never the submitted path."""
    monitor = scope.get(MONITOR_SCOPE_KEY) or {}
    child_route = monitor.get("route")
    if child_route == UNMATCHED_ROUTE:
        return UNMATCHED_ROUTE
    if isinstance(child_route, str) and child_route.startswith("/"):
        slug = monitor.get("module_slug") or ""
        value = f"/api/module/{slug}{child_route}" if slug else child_route
        return _bounded_route(value)

    route = scope.get("route")
    template = getattr(route, "path", None)
    if template and template != "/api/module":
        root_path = scope.get("root_path") or ""
        if root_path and not template.startswith(root_path):
            template = root_path + template
        return _bounded_route(template) if template.startswith("/api/") else UNMATCHED_ROUTE

    for candidate in routes:
        try:
            match, _ = candidate.matches(scope)
        except Exception:
            continue
        candidate_path = getattr(candidate, "path", None)
        if (
            match == Match.FULL
            and candidate_path
            and candidate_path != "/api/module"
            and candidate_path.startswith("/api/")
        ):
            return _bounded_route(candidate_path)
    return UNMATCHED_ROUTE


class ApiLatencyMiddleware:
    """Record one fail-open event after an eligible response finishes."""

    def __init__(self, app, routes: Callable[[], Iterable]):
        self.app = app
        self.routes = routes

    async def __call__(self, scope, receive, send):
        if not should_capture(scope):
            await self.app(scope, receive, send)
            return

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        finished = None
        status = None
        disconnected = False
        completion = "normal"
        scope[MONITOR_SCOPE_KEY] = {}

        async def monitored_receive():
            nonlocal disconnected
            message = await receive()
            if message.get("type") == "http.disconnect":
                disconnected = True
            return message

        async def monitored_send(message):
            nonlocal disconnected, finished, status
            if message.get("type") == "http.response.start":
                status = message.get("status")
            try:
                await send(message)
            except OSError:
                disconnected = True
                raise
            if (
                message.get("type") == "http.response.body"
                and not message.get("more_body", False)
            ):
                finished = time.monotonic()

        try:
            await self.app(scope, monitored_receive, monitored_send)
            if disconnected:
                completion = "disconnect"
        except asyncio.CancelledError:
            completion = "disconnect" if disconnected else "cancelled"
            raise
        except Exception:
            completion = "disconnect" if disconnected else "internal_failure"
            if finished is None and not disconnected:
                status = 500
            raise
        finally:
            try:
                ended = finished if finished is not None else time.monotonic()
                monitor = scope.get(MONITOR_SCOPE_KEY) or {}
                if completion == "normal" and finished is None:
                    completion = "disconnect" if disconnected else "internal_failure"
                latency_service.capture({
                    "started_at": started_at,
                    "duration_ms": max(0.0, (ended - started) * 1000.0),
                    "method": normalize_method(scope.get("method")),
                    "route": matched_route_template(scope, self.routes()),
                    "status_class": normalize_status_class(status),
                    "completion": normalize_completion(completion),
                    "module_slug": monitor.get("module_slug") or "",
                })
            except Exception as err:
                try:
                    logger.warning(
                        "api latency capture failed completion={} error_type={}",
                        completion,
                        type(err).__name__,
                    )
                except Exception:
                    pass
