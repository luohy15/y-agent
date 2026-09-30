import os
import re

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.middleware.mcp_access_log import MCP_OAUTH_CALLBACK_PATH
from api.middleware.provider_status_access_log import PROVIDER_STATUS_WEBHOOK_PREFIX

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"

PUBLIC_PREFIXES = ("/api/auth", "/api/telegram/webhook", "/api/health", "/docs", "/openapi.json")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # The opaque path credential is validated by the dedicated receiver. This
        # is deliberately not a broad public /api/provider-status prefix.
        if request.method == "POST" and path.startswith(PROVIDER_STATUS_WEBHOOK_PREFIX):
            return await call_next(request)

        # The single-use OAuth state is the credential for the provider
        # redirect (todo 3796). Exact GET path only; every other MCP route
        # stays authenticated.
        if request.method == "GET" and path == MCP_OAUTH_CALLBACK_PATH:
            return await call_next(request)

        # This exact route authenticates an opaque, launch-scoped grant, not JWT.
        if request.method == "POST" and re.fullmatch(
                r"/api/mcp/runtime/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path):
            return await call_next(request)

        # Allow public routes
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
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

        request.state.user_id = payload["user_id"]
        request.state.email = payload.get("email", "")
        return await call_next(request)
