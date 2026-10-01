"""Host MCP routes (todo 3796).

Only the launch-scoped runtime gateway lives here; it authenticates the
per-launch grant instead of a JWT. There is no OAuth callback route: the
module CLI catches the RFC 8252 loopback redirect and completes it through the
JWT-authenticated `mcp` module (todo 3796 round 2). Connector management
stays behind that module.
"""

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from storage.service.mcp import McpError

router = APIRouter(prefix="/mcp")

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.post("/runtime/{launch_id}")
async def runtime(launch_id: str, request: Request):
    from agent.mcp import gateway

    try:
        auth = request.headers.get("authorization", "")
        if request.query_params or not auth.startswith("Bearer ") or len(auth) > 256:
            raise McpError("forbidden", "launch grant is required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > gateway.MAX_REQUEST_BYTES:
                raise McpError("invalid_input", "runtime request is too large")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise McpError("invalid_input", "invalid runtime request") from None
        result = await asyncio.to_thread(gateway.dispatch, launch_id, auth[7:], body)
        return JSONResponse({"result": result}, headers=_NO_STORE_HEADERS)
    except McpError as err:
        # Even unexpected provider/DB exception text must never reach the VM.
        return JSONResponse({"error": {"code": err.code,
                             "message": "Connector unavailable. Retry or reconnect in MCP settings."}},
                            status_code=err.status, headers=_NO_STORE_HEADERS)
    except Exception:
        return JSONResponse({"error": {"code": "provider_unavailable",
                             "message": "Connector unavailable. Retry in MCP settings."}},
                            status_code=503, headers=_NO_STORE_HEADERS)
