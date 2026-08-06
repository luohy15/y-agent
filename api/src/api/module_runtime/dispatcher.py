"""Raw ASGI dispatcher for `/api/module/{slug}/…` (plan 3.4 / D13).

Mounted at `/api/module` *after* the management APIRouter is included, so
routes like `/api/module/list` win. This app only handles non-reserved slugs
and forwards the (same) ASGI scope to the per-version sub-app after stripping
the slug segment. request.state set by AuthMiddleware is expected to survive
because Starlette backs Request.state with scope["state"] (assumption A1).
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from agent.module_host import request_owner
from api.controller.module import RESERVED_SLUGS, SLUG_RE, default_owner_user_id
from api.module_runtime import loader
from api.module_runtime.errors import ModuleRuntimeError


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


def _status_for(err: ModuleRuntimeError) -> int:
    if err.kind in ("not_found", "no_api"):
        return 404
    if err.kind in ("disabled", "archive"):
        # archive: an unsafe or oversized bundle is a client problem (400),
        # surfaced here as a 4xx so unrelated routes stay healthy.
        return 400 if err.kind == "archive" else 403
    if err.kind == "backend_version":
        return 409
    if err.kind in ("hash_mismatch", "import", "fetch"):
        return 502
    return 500


def _user_id_from_scope(scope: dict) -> Optional[int]:
    state = scope.get("state")
    if state is None:
        return None
    # Starlette may give a State object or a plain dict/namespace.
    user_id = getattr(state, "user_id", None)
    if user_id is None and isinstance(state, dict):
        user_id = state.get("user_id")
    return user_id


class ModuleDispatcher:
    """ASGI app: parse slug, load active module, forward remaining path."""

    def __init__(self, load_fn: Callable = None, resolve_fn: Callable = None):
        # Injectable for tests. The production loader consumes the version this
        # dispatcher already resolved, avoiding a second active-pointer query.
        self._load = (
            (lambda user_id, slug, _version: load_fn(user_id, slug))
            if load_fn
            else (lambda _user_id, slug, version: loader.load_module_version(slug, version))
        )
        self._resolve = resolve_fn or loader.resolve_active_version

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return

        path = scope.get("path") or ""
        # Starlette Mount normally strips the mount point so we see
        # `/{slug}/…`. Some callers (and defence-in-depth for double mounts)
        # may forward the full `/api/module/{slug}/…` path — accept both.
        if path.startswith("/api/module/"):
            path = path[len("/api/module"):] or "/"
        elif path == "/api/module":
            path = "/"
        # path is now `/{slug}/…` or `/{slug}` or `/`.
        stripped = path[1:] if path.startswith("/") else path
        if not stripped:
            await _send_json(
                send,
                404,
                {"detail": "module slug required under /api/module/{slug}/…"},
            )
            return

        parts = stripped.split("/", 1)
        slug = parts[0]
        rest = "/" + parts[1] if len(parts) > 1 else "/"

        if slug in RESERVED_SLUGS:
            # Management routes should have matched already; if we got here the
            # mount stole the request — refuse rather than treat as a module.
            await _send_json(
                send,
                404,
                {"detail": f"{slug!r} is a management route, not a module slug"},
            )
            return

        if not SLUG_RE.match(slug):
            await _send_json(send, 400, {"detail": "Invalid slug"})
            return

        user_id = _user_id_from_scope(scope)
        if user_id is None:
            await _send_json(send, 401, {"detail": "Not authenticated"})
            return
        owner_id = default_owner_user_id()
        if owner_id is None:
            await _send_json(
                send,
                403,
                {"detail": "backend module dispatch requires a configured maintainer account"},
            )
            return

        try:
            version = self._resolve(owner_id, slug)
        except ModuleRuntimeError as err:
            await _send_json(send, _status_for(err), err.detail())
            return

        if user_id != owner_id and version.dispatch_scope != "authenticated":
            await _send_json(
                send,
                403,
                {"detail": "backend module dispatch is restricted to the maintainer account"},
            )
            return

        try:
            loaded = self._load(owner_id, slug, version)
        except ModuleRuntimeError as err:
            await _send_json(send, _status_for(err), err.detail())
            return

        # Forward the same scope (preserving state / request.state) with the
        # slug segment stripped so the module router sees `/ping` not `/finance/ping`.
        child_scope = dict(scope)
        child_scope["path"] = rest
        child_scope["raw_path"] = rest.encode("utf-8")
        # root_path comes from Starlette Mount already carrying `/api/module`;
        # append only the slug so modules observing scope['root_path'] (OpenAPI
        # server paths, url_for, middleware) see `/api/module/<slug>` rather than
        # a duplicated `/api/module/api/module/<slug>` (review finding 6).
        child_scope["root_path"] = (scope.get("root_path") or "") + "/" + slug

        # Bind the authenticated owner for handler tasks so the request-bound
        # run_vm_command capability cannot be steered at a caller-chosen user.
        with request_owner(user_id):
            await loaded.app(child_scope, receive, send)


module_dispatcher = ModuleDispatcher()
