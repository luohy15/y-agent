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


_MEDIA_KINDS = {2: "image", 3: "voice", 4: "file", 5: "video"}
_TEXT_LIMIT = 64000
_NAME_LIMIT = 1024
_ID_LIMIT = 256


def _clip(value, limit):
    """A stripped string clamped to the API's field limit, or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _id_clip(value):
    """A provider id as a stripped string; `0` is a valid id."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int)):
        return None
    return _clip(str(value), _ID_LIMIT)


def _item_media(item):
    """`(media_kind, media_name)` for a non-text item, else `(None, None)`."""
    kind = _MEDIA_KINDS.get(item.get("type"))
    if not kind:
        return ("attachment", None) if item.get("type") not in (None, 1) else (None, None)
    if kind == "file":
        return kind, _clip((item.get("file_item") or {}).get("file_name"), _NAME_LIMIT)
    return kind, None


def _item_text(item):
    """Inline text: a text item's body, else a voice item's transcript."""
    text = (item.get("text_item") or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        text = (item.get("voice_item") or {}).get("text")
    return _clip(text, _TEXT_LIMIT)


def _partial_text(value):
    """Only a complete, well-typed selected-substring payload; else None.

    Both tokens and both occurrence indexes are required, so an odd client
    payload never reaches the API as a malformed quote.
    """
    if not isinstance(value, dict):
        return None
    out = {}
    for key in ("start", "end"):
        text = _clip(value.get(key), _TEXT_LIMIT)
        if not text:
            return None
        out[key] = text
    for key in ("startindex", "endindex"):
        index = value.get(key)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return None
        out[key] = index
    digest = _clip(value.get("quotemd5"), 64)
    if digest:
        out["quotemd5"] = digest.lower()
    return out


def _quote(item):
    """Structured quote from one inbound item's `ref_msg`, or None.

    Keeps the inline text, voice transcript, title, media hint and
    selected-substring payload; `svr_id` is forwarded even when the newer
    client omits the content.
    """
    ref = item.get("ref_msg") or {}
    if not ref:
        return None
    message_item = ref.get("message_item") or {}
    body = _item_text(message_item)
    title = _clip(ref.get("title"), _TEXT_LIMIT)
    media_kind, media_name = _item_media(message_item)
    quote = {}
    svr_id = _id_clip(ref.get("svr_id"))
    if svr_id:
        quote["svr_id"] = svr_id
    if body:
        quote["text"] = body
    if title and title != body:
        quote["title"] = title
    if media_kind:
        quote["media_kind"] = media_kind
    if media_name:
        quote["media_name"] = media_name
    partial = _partial_text(ref.get("partial_text"))
    if partial:
        quote["partial_text"] = partial
    return quote or None


def inbound(msg, account):
    if msg.get("message_type") != 1 or msg.get("group_id") or msg.get("from_user_id") == account:
        return None
    if not msg.get("from_user_id") or msg.get("message_id") is None:
        raise ValueError("Missing provider message identity")
    items = msg.get("item_list") or []
    texts = []
    quote = None
    media_kind, media_name = None, None
    for item in items:
        if quote is None:
            quote = _quote(item)
        if item.get("type") == 1:
            texts.append((item.get("text_item") or {}).get("text", ""))
            continue
        if item.get("type") == 3:
            # Keep a voice transcript so an ID-only quote of this message still
            # shows it; the message itself stays a media notice.
            texts.append(_item_text(item) or "")
            if media_kind is None:
                media_kind, media_name = _item_media(item)
            continue
        if media_kind is None:
            media_kind, media_name = _item_media(item)
    text = "\n".join(texts)[:_TEXT_LIMIT]
    return {"peer": msg["from_user_id"], "message_id": str(msg["message_id"]),
            "context_token": msg.get("context_token"), "text": text,
            "media": not items or any(item.get("type") != 1 for item in items),
            "media_kind": media_kind, "media_name": media_name, "quote": quote}


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
                        receipts = state.setdefault("sent_unacked", {})
                        if not isinstance(receipts, dict):
                            receipts = {str(key): None for key in receipts}
                            state["sent_unacked"] = receipts
                        ok = row["outbox_id"] in receipts
                        if not ok:
                            try:
                                provider_message_id = client.send(row)
                            except ProviderError as exc:
                                if exc.code == -14:
                                    raise
                            else:
                                ok = True
                                receipts[row["outbox_id"]] = provider_message_id
                                save(path, state)
                        ack = {"outbox_id": row["outbox_id"], "lease": row["lease"], "ok": ok}
                        if receipts.get(row["outbox_id"]):
                            ack["provider_message_id"] = receipts[row["outbox_id"]]
                        api("ack", ack)
                        if ok:
                            receipts.pop(row["outbox_id"], None)
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
