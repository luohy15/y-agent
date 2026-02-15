import os

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"

PUBLIC_PREFIXES = ("/api/auth", "/docs", "/openapi.json")

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow public routes
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow public share GET endpoint
        if path == "/api/chat/share" and request.method == "GET":
            return await call_next(request)

        # Allow static files (served at root by StaticFiles mount)
        if not path.startswith("/api/chat") and not path.startswith("/api/file"):
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
