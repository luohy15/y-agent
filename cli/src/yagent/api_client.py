"""API client for authenticated requests to the y-agent API."""

import json
import os
import sys

import httpx


AUTH_FILE = os.path.join(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")), "auth.json")
DEFAULT_WEB_URL = "https://yovy.app"


def load_auth() -> dict:
    """Load auth credentials from auth.json. Returns dict with token, email, api_url."""
    if not os.path.exists(AUTH_FILE):
        print("Not logged in. Run 'y login' first.", file=sys.stderr)
        sys.exit(1)
    with open(AUTH_FILE) as f:
        return json.load(f)


def save_auth(token: str, email: str, web_url: str):
    """Save auth credentials to auth.json."""
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump({"token": token, "email": email, "web_url": web_url}, f)


def remove_auth():
    """Remove auth.json."""
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)


def resolve_api_auth() -> tuple:
    """Base URL and bearer token from Y_API_BASE or the stored login.

    Y_API_BASE with Y_USER_ID signs a JWT from JWT_SECRET_KEY. Otherwise the
    stored auth.json supplies web_url and token. The token is never included
    in an error string by this helper.
    """
    api_url = os.getenv("Y_API_BASE")
    if api_url:
        user_id = os.getenv("Y_USER_ID")
        if user_id:
            import jwt as pyjwt
            token = pyjwt.encode({"user_id": int(user_id)}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        else:
            token = load_auth().get("token", "")
    else:
        auth = load_auth()
        api_url = auth.get("web_url", DEFAULT_WEB_URL)
        token = auth["token"]
    return api_url.rstrip("/"), token


def api_request(method: str, path: str, timeout: float = 30, **kwargs) -> httpx.Response:
    """Make an authenticated API request.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g. /api/todo/list)
        timeout: request timeout in seconds (default 30)
        **kwargs: passed to httpx.request (params, json, etc.)
    """
    api_url, token = resolve_api_auth()
    url = f"{api_url}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.request(method, url, headers=headers, timeout=timeout, **kwargs)

    if resp.status_code == 401:
        print("Session expired. Run 'y login' to re-authenticate.", file=sys.stderr)
        sys.exit(1)

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {path}: {_http_error_detail(resp)}",
            request=exc.request,
            response=resp,
        ) from exc
    return resp


def api_request_json(method: str, path: str, *, payload: bytes, timeout: float) -> dict:
    """Stream one module JSON object within the shared bounds (todo 3838).

    Uses the same credentials as `api_request`, keeps its 401 behavior, never
    follows a redirect, and stops reading at the byte cap or the total
    deadline. Errors never include the token. `payload` comes from
    `agent.module_json.validate_request`.
    """
    import time

    from agent.module_json import (
        JSON_MAX_BYTES,
        ModuleJsonError,
        check_declared_length,
        check_media_type,
        check_status,
        decode_object,
    )

    deadline = time.monotonic() + timeout
    api_url, token = resolve_api_auth()
    headers = {"Authorization": f"Bearer {token}"}
    if payload:
        headers["Content-Type"] = "application/json"
    chunks = []
    received = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream(method, f"{api_url}{path}", content=payload or None, headers=headers) as response:
                if response.status_code == 401:
                    print("Session expired. Run 'y login' to re-authenticate.", file=sys.stderr)
                    sys.exit(1)
                check_status(response.status_code)
                check_media_type(response.headers.get("content-type", ""), response.status_code)
                check_declared_length(response.headers.get("content-length"))
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise ModuleJsonError("timeout", "module JSON call timed out")
                    if received + len(chunk) > JSON_MAX_BYTES:
                        raise ModuleJsonError("size", "module JSON response exceeds the size limit")
                    received += len(chunk)
                    chunks.append(chunk)
                status = response.status_code
    except httpx.TimeoutException:
        raise ModuleJsonError("timeout", "module JSON call timed out") from None
    except httpx.HTTPError as exc:
        raise ModuleJsonError("transport", f"module JSON call failed: {type(exc).__name__}") from None
    return decode_object(b"".join(chunks), status)


def _http_error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (resp.text or "")[:200]
