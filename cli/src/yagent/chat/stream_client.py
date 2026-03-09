"""SSE streaming client for consuming chat messages from the API."""

import json
import os
import sys

import httpx

from storage.entity.dto import Message
from yagent.api_client import load_auth
from yagent.display_manager import DisplayManager


def _get_api_url_and_token():
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
        api_url = auth.get("api_url", "https://yovy.app")
        token = auth["token"]
    return api_url, token


def stream_chat(chat_id: str, display_manager: DisplayManager, last_index: int = 0):
    """Connect to SSE stream, display messages, return final index.

    Returns:
        tuple: (last_index, status) where status is "done", "ask", or "interrupted"
    """
    api_url, token = _get_api_url_and_token()
    url = f"{api_url}/api/chat/messages"
    params = {"chat_id": chat_id, "last_index": last_index}
    headers = {"Authorization": f"Bearer {token}"}

    event_type = None
    data_buf = None

    try:
        with httpx.stream("GET", url, params=params, headers=headers, timeout=None) as resp:
            if resp.status_code == 401:
                print("Session expired. Run 'y login' to re-authenticate.", file=sys.stderr)
                sys.exit(1)
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue

                if line.startswith("data:"):
                    data_buf = line[len("data:"):].strip()

                    if event_type == "message":
                        payload = json.loads(data_buf)
                        msg = Message.from_dict(payload["data"])
                        last_index = payload["index"] + 1
                        display_manager.display_message_panel(msg)

                    elif event_type == "ask":
                        return last_index, "ask", json.loads(data_buf)

                    elif event_type == "done":
                        payload = json.loads(data_buf)
                        return last_index, "done", payload

                    elif event_type == "error":
                        payload = json.loads(data_buf)
                        display_manager.print_error(payload.get("error", "Unknown error"))
                        return last_index, "error", payload

                    event_type = None
                    data_buf = None

    except KeyboardInterrupt:
        return last_index, "interrupted", None

    return last_index, "done", None
