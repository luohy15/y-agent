"""API client for authenticated requests to the y-agent API."""

import json
import os
import sys

import httpx


AUTH_FILE = os.path.join(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")), "auth.json")
DEFAULT_API_URL = "https://yovy.app"


def load_auth() -> dict:
    """Load auth credentials from auth.json. Returns dict with token, email, api_url."""
    if not os.path.exists(AUTH_FILE):
        print("Not logged in. Run 'y login' first.", file=sys.stderr)
        sys.exit(1)
    with open(AUTH_FILE) as f:
        return json.load(f)


def save_auth(token: str, email: str, api_url: str):
    """Save auth credentials to auth.json."""
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump({"token": token, "email": email, "api_url": api_url}, f)


def remove_auth():
    """Remove auth.json."""
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)


def api_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Make an authenticated API request.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g. /api/todo/list)
        **kwargs: passed to httpx.request (params, json, etc.)
    """
    auth = load_auth()
    api_url = auth.get("api_url", DEFAULT_API_URL)
    token = auth["token"]

    url = f"{api_url}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.request(method, url, headers=headers, timeout=30, **kwargs)

    if resp.status_code == 401:
        print("Session expired. Run 'y login' to re-authenticate.", file=sys.stderr)
        sys.exit(1)

    resp.raise_for_status()
    return resp
