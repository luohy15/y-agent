import os
import re

import jwt
from loguru import logger
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.util.access_http import access_json
from storage.service.user_access import request_admitted

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"

PUBLIC_PREFIXES = ("/api/auth", "/api/telegram/webhook", "/api/health", "/docs", "/openapi.json")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # This exact route authenticates an opaque, launch-scoped grant, not JWT.
        if request.method == "POST" and re.fullmatch(
                r"/api/mcp/runtime/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path):
            return await call_next(request)

        # Allow public routes
        if request.method == "POST" and path in {
            "/api/wechat/bridge/inbound", "/api/wechat/bridge/claim",
            "/api/wechat/bridge/ack", "/api/wechat/bridge/heartbeat",
        }:
            return await call_next(request)

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Verified-email waitlist application. Every other /api/access route is protected.
        if request.method == "POST" and path == "/api/access/request":
            return await call_next(request)

        # Allow public share GET endpoints
        if path == "/api/chat/share" and request.method == "GET":
            return await call_next(request)
        if path == "/api/trace/share" and request.method == "GET":
            return await call_next(request)
        if path == "/api/note/share" and request.method == "GET":
            return await call_next(request)

        # Protected routes require JWT (header or query param for SSE)
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.query_params.get("token")

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except jwt.InvalidTokenError:
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})

        user_id = payload.get("user_id")
        email = payload.get("email") or ""
        try:
            decision = await run_in_threadpool(request_admitted, user_id, email)
        except Exception:
            logger.exception("admission check failed closed")
            decision = {"admitted": False, "state": "required"}
        if not decision.get("admitted"):
            state = decision.get("state") if decision.get("state") in {"pending", "required"} else "required"
            logger.info(
                "access denied user_id={} email={} code=access_not_approved state={}",
                user_id,
                email,
                state,
            )
            return access_json(403, "Access not approved.", "access_not_approved", state)

        request.state.user_id = user_id
        request.state.email = email
        return await call_next(request)
