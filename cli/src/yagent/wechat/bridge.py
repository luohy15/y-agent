import fcntl
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from yagent.wechat.client import Client, ProviderError


def state_path(bot):
    if not re.fullmatch(r"[A-Za-z0-9_@-]{1,160}", bot):
        raise ValueError("Invalid bot name")
    return Path.home() / ".y-agent" / "wechat" / (bot + ".json")


@contextmanager
def exclusive(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another login or bridge is running for this bot") from None
        yield


def save(path, state):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        try:
            temp.write(json.dumps(state).encode())
            temp.flush()
            os.fsync(temp.fileno())
            os.replace(temp.name, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def inbound(msg, account):
    if msg.get("message_type") != 1 or msg.get("group_id") or msg.get("from_user_id") == account:
        return None
    if not msg.get("from_user_id") or msg.get("message_id") is None:
        raise ValueError("Missing provider message identity")
    items = msg.get("item_list") or []
    lines = []
    for item in items:
        ref = item.get("ref_msg") or {}
        quote = ((ref.get("message_item") or {}).get("text_item") or {}).get("text") or ref.get("title")
        if quote:
            lines.extend("> " + line for line in quote.splitlines())
        if item.get("type") == 1:
            lines.append((item.get("text_item") or {}).get("text", ""))
    return {"peer": msg["from_user_id"], "message_id": str(msg["message_id"]),
            "context_token": msg.get("context_token"), "text": "\n".join(lines),
            "media": not items or any(item.get("type") != 1 for item in items)}


def run(path):
    with exclusive(path), httpx.Client(follow_redirects=False) as http:
        state = json.loads(path.read_bytes())
        if path.stat().st_mode & 0o077 or urlsplit(state["api"]).scheme != "https":
            raise ValueError("Bridge requires private state and HTTPS API")
        client = Client(http, state["baseurl"], state["bot_token"])

        def api(action, body=None):
            response = http.post(state["api"] + "/api/wechat/bridge/" + action, json=body or {},
                                 headers={"Authorization": "Bearer " + state["bridge_token"]}, timeout=40)
            if response.status_code in (401, 403):
                raise ValueError("Bridge revoked or access denied")
            response.raise_for_status()
            return response.json()

        timeout = 35
        started = False
        try:
            while True:
                try:
                    api("heartbeat")
                    if time.time() < state.get("paused_until", 0):
                        time.sleep(30)
                        continue
                    if not started:
                        client.post("msg/notifystart", {})
                        started = True
                    for _ in range(100):
                        row = api("claim")["item"]
                        if not row:
                            break
                        receipts = state.setdefault("sent_unacked", [])
                        ok = row["outbox_id"] in receipts
                        if not ok:
                            try:
                                client.send(row)
                            except ProviderError as exc:
                                if exc.code == -14:
                                    raise
                            else:
                                ok = True
                                receipts.append(row["outbox_id"])
                                save(path, state)
                        api("ack", {"outbox_id": row["outbox_id"], "lease": row["lease"], "ok": ok})
                        if ok:
                            receipts.remove(row["outbox_id"])
                            save(path, state)
                    batch = client.post("getupdates", {"get_updates_buf": state["get_updates_buf"]}, timeout+5)
                    for msg in batch.get("msgs") or []:
                        payload = inbound(msg, state["ilink_bot_id"])
                        if payload:
                            api("inbound", payload)
                    if batch.get("get_updates_buf"):
                        state["get_updates_buf"] = batch["get_updates_buf"]
                        save(path, state)
                    api("heartbeat", {"polled": True})
                    timeout = min(120, max(1, (batch.get("longpolling_timeout_ms") or 35000)/1000))
                except ProviderError as exc:
                    if exc.code == -14:
                        state["paused_until"] = time.time() + 3600
                        save(path, state)
                    time.sleep(3)
                except httpx.HTTPError:
                    time.sleep(3)
        finally:
            if started:
                with suppress(httpx.HTTPError, ProviderError):
                    client.post("msg/notifystop", {})
