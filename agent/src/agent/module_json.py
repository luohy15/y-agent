"""Shared policy for owner-bound JSON calls into a published module (todo 3838).

Importable by both runtimes. The API adapter (`api.module_runtime.json_call`,
in-process ASGI) and the CLI adapter (`yagent.api_client.api_request_json`,
streaming HTTP) both validate requests and decode responses here, so the
method, path, size, deadline and media-type rules cannot drift apart.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

JSON_MAX_BYTES = 1_048_576
JSON_TIMEOUT_SECONDS = 5.0
JSON_MAX_DEPTH = 2
JSON_METHODS = frozenset({"GET", "POST"})

# Local absolute path: unreserved characters and `/` only. No scheme, host,
# query, fragment, percent-encoding or backslash; `//` and dot segments fail.
_PATH = re.compile(r"^/[A-Za-z0-9._~\-/]{0,511}$")


class ModuleJsonError(Exception):
    """A refused or failed module JSON call. Messages never carry credentials."""

    def __init__(self, code: str, message: str, *, status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


def validate_request(user_id, method: str, path: str, body, timeout) -> bytes:
    """Check one call against the shared policy and return the encoded body."""
    if type(user_id) is not int:
        raise ModuleJsonError("owner", "module JSON calls are owner-bound")
    if method not in JSON_METHODS:
        raise ModuleJsonError("method", "only GET and POST JSON routes are allowed")
    if (
        not isinstance(path, str)
        or not _PATH.match(path)
        or path.startswith("//")
        or any(segment in (".", "..") for segment in path.split("/"))
    ):
        raise ModuleJsonError("path", "module JSON paths must be absolute and local")
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or timeout <= 0
        or timeout > JSON_TIMEOUT_SECONDS
    ):
        raise ModuleJsonError("timeout", "module JSON timeout must be finite and at most 5 seconds")
    if body is None:
        return b""
    if method == "GET":
        raise ModuleJsonError("body", "GET module JSON calls take no body")
    if not isinstance(body, dict):
        raise ModuleJsonError("body", "module JSON bodies must be objects")
    try:
        payload = json.dumps(body, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModuleJsonError("body", "module JSON body is not serializable") from exc
    if len(payload) > JSON_MAX_BYTES:
        raise ModuleJsonError("size", "module JSON request exceeds the size limit")
    return payload


def check_declared_length(value: Optional[str]) -> None:
    """Refuse a malformed or over-cap Content-Length before reading the body."""
    if value is None:
        return
    try:
        declared = int(value)
    except ValueError as exc:
        raise ModuleJsonError("size", "module JSON response length is malformed") from exc
    if declared < 0 or declared > JSON_MAX_BYTES:
        raise ModuleJsonError("size", "module JSON response exceeds the size limit")


def check_status(status: int) -> None:
    if 300 <= status < 400:
        raise ModuleJsonError("redirect", "module JSON calls do not follow redirects", status=status)
    if status == 403:
        raise ModuleJsonError("forbidden", "module JSON call was not allowed", status=status)
    if status == 404:
        raise ModuleJsonError("not_found", "module JSON route was not found", status=status)
    if status >= 400:
        raise ModuleJsonError("upstream", "module JSON call failed", status=status)


def check_media_type(content_type: str, status: int = 0) -> None:
    if (content_type or "").split(";")[0].strip().lower() != "application/json":
        raise ModuleJsonError("content_type", "module JSON calls accept only JSON responses", status=status)


def decode_object(raw: bytes, status: int = 0) -> dict[str, Any]:
    if len(raw) > JSON_MAX_BYTES:
        raise ModuleJsonError("size", "module JSON response exceeds the size limit", status=status)
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModuleJsonError("content_type", "module JSON response was not an object", status=status) from exc
    if not isinstance(parsed, dict):
        raise ModuleJsonError("content_type", "module JSON response was not an object", status=status)
    return parsed
