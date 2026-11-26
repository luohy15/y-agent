import fcntl
import json
import os
import re
import sys
import tempfile
import threading
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
_PAYLOAD_KINDS = (("image_item", "image"), ("voice_item", "voice"),
                  ("file_item", "file"), ("video_item", "video"))
_TEXT_LIMIT = 64000
_NAME_LIMIT = 1024
_ID_LIMIT = 256
_MEDIA_ITEMS_LIMIT = 9
_MEDIA_URL_LIMIT = 4096
_MEDIA_KEY_LIMIT = 256
_MEDIA_SIZE_RE = re.compile(r"[0-9]{1,18}")


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


def _present(value):
    """A `None` or empty-dict payload is absent; `0` and `""` stay present."""
    return value is not None and value != {}


def _payload_keys(item):
    """Present `*_item` payload keys, excluding the text body."""
    return sorted(key for key, value in item.items()
                  if key.endswith("_item") and key != "text_item" and _present(value))


def _item_media(item):
    """`(media_kind, media_name)` for one inbound item.

    An explicit `type` wins: `1` is text even beside an empty media stub, `2`
    through `5` are image / voice / file / video, and any other non-text type
    is an attachment. Only a zero or absent `type` falls back to the payload
    key, because live clients quote media without a type; an empty stub does
    not count, and any other non-text payload stays an attachment.
    """
    if not isinstance(item, dict):
        return None, None
    item_type = item.get("type")
    if item_type == 1:
        return None, None
    kind = _MEDIA_KINDS.get(item_type)
    if not kind:
        if item_type not in (None, 0):
            return "attachment", None
        kind = next((name for key, name in _PAYLOAD_KINDS if _present(item.get(key))), None)
        if not kind:
            return ("attachment", None) if _payload_keys(item) else (None, None)
    if kind == "file":
        file_item = item.get("file_item")
        if not isinstance(file_item, dict):
            file_item = {}
        name = (_clip(file_item.get("file_name"), _NAME_LIMIT)
                or _clip(file_item.get("name"), _NAME_LIMIT))
        return kind, name
    return kind, None


def _item_text(item):
    """Inline text: a text item's body, else a voice item's transcript."""
    if not isinstance(item, dict):
        return None
    text_item = item.get("text_item")
    text = text_item.get("text") if isinstance(text_item, dict) else None
    if not isinstance(text, str) or not text.strip():
        voice_item = item.get("voice_item")
        text = voice_item.get("text") if isinstance(voice_item, dict) else None
    return _clip(text, _TEXT_LIMIT)


def _media_size(value):
    """A non-negative declared byte count from an int or a bounded digit string.

    The provider controls `len`, and `str.isdigit()` accepts characters `int()`
    rejects (`"²"`), so match ASCII digits only. The length bound keeps an
    absurd digit string from hitting `int()`'s own conversion limit.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if _MEDIA_SIZE_RE.fullmatch(text):
            return int(text)
    return None


def _media_items(items):
    """Up to nine image/file/voice CDN descriptors for one inbound message.

    Only what the API needs to fetch, decrypt and transcribe is forwarded:
    kind, the CDN url or query param, both AES key spellings, a file's name and
    declared size, and for a voice note its declared duration, codec and sample
    rate. The nested `media` object wins over an item-level fallback.
    """
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind, _name = _item_media(item)
        if kind not in ("image", "file", "voice"):
            continue
        payload = item.get(kind + "_item")
        if not isinstance(payload, dict):
            payload = {}
        media = payload.get("media")
        if not isinstance(media, dict):
            media = {}
        descriptor = {"kind": kind}
        for field in ("full_url", "encrypt_query_param"):
            value = _clip(media.get(field), _MEDIA_URL_LIMIT) or _clip(
                payload.get(field), _MEDIA_URL_LIMIT)
            if value:
                descriptor[field] = value
        aeskey = _clip(payload.get("aeskey"), _MEDIA_KEY_LIMIT) or _clip(
            media.get("aeskey"), _MEDIA_KEY_LIMIT)
        if aeskey:
            descriptor["aeskey"] = aeskey
        aes_key = _clip(media.get("aes_key"), _MEDIA_KEY_LIMIT) or _clip(
            payload.get("aes_key"), _MEDIA_KEY_LIMIT)
        if aes_key:
            descriptor["aes_key"] = aes_key
        if kind == "file":
            name = (_clip(payload.get("file_name"), _NAME_LIMIT)
                    or _clip(payload.get("name"), _NAME_LIMIT))
            if name:
                descriptor["file_name"] = name
            size = _media_size(payload.get("len"))
            if size is not None:
                descriptor["size"] = size
        elif kind == "voice":
            duration = _media_size(payload.get("playtime"))
            if duration is not None:
                descriptor["duration_ms"] = duration
            encode_type = _media_size(payload.get("encode_type"))
            if encode_type is not None:
                descriptor["encode_type"] = encode_type
            sample_rate = _media_size(payload.get("sample_rate"))
            if sample_rate is not None:
                descriptor["sample_rate"] = sample_rate
        if "full_url" not in descriptor and "encrypt_query_param" not in descriptor:
            continue
        out.append(descriptor)
        if len(out) >= _MEDIA_ITEMS_LIMIT:
            break
    return out


def _media_shape(item):
    """Present payload key -> its nested `media` key names, never values."""
    out = {}
    for key in _payload_keys(item):
        payload = item.get(key)
        media = payload.get("media") if isinstance(payload, dict) else None
        if isinstance(media, dict) and media:
            out[key] = sorted(name for name, value in media.items() if value is not None)
    return out


def _shape(item):
    """Diagnostic shape of one item: type, present keys and payload keys."""
    shape = {"type": item.get("type"),
             "keys": sorted(key for key, value in item.items() if value is not None)}
    payload = _payload_keys(item)
    if payload:
        shape["payload"] = payload
    media = _media_shape(item)
    if media:
        shape["media"] = media
    return shape


def _ref_shape(item):
    """One quoted reference: `ref_msg` keys and its message item shape."""
    ref = item["ref_msg"]
    shape = {"keys": sorted(key for key, value in ref.items() if value is not None)}
    message_item = ref.get("message_item")
    if isinstance(message_item, dict) and message_item:
        shape["item"] = {"type": message_item.get("type"),
                         "keys": sorted(key for key, value in message_item.items()
                                        if value is not None)}
        payload = _payload_keys(message_item)
        if payload:
            shape["payload"] = payload
    return shape


def _log_shape(items):
    """One content-free journald line per quoted or media message."""
    refs = [_ref_shape(item) for item in items
            if isinstance(item, dict) and isinstance(item.get("ref_msg"), dict) and item["ref_msg"]]
    media = [_shape(item) for item in items
             if isinstance(item, dict) and _item_media(item)[0] is not None]
    if not refs and not media:
        return
    print("bridge shape", json.dumps({"refs": refs, "media": media}, ensure_ascii=False),
          file=sys.stderr, flush=True)


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
    if not isinstance(item, dict):
        return None
    ref = item.get("ref_msg")
    if not isinstance(ref, dict) or not ref:
        return None
    message_item = ref.get("message_item")
    if not isinstance(message_item, dict):
        message_item = {}
    body = _item_text(message_item)
    title = _clip(ref.get("title"), _TEXT_LIMIT)
    media_kind, media_name = _item_media(message_item)
    quote = {}
    svr_id = _id_clip(ref.get("svr_id")) or _id_clip(message_item.get("msg_id"))
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
    _log_shape(items)
    texts = []
    quote = None
    media_kind, media_name = None, None
    media = not items
    for item in items:
        if not isinstance(item, dict):
            continue
        if quote is None:
            quote = _quote(item)
        kind, name = _item_media(item)
        if kind is not None:
            media = True
            if media_kind is None:
                media_kind, media_name = kind, name
            if kind == "voice" and not _media_items([item]):
                # No CDN descriptor: keep the client transcript so the API can
                # still deliver it. With a descriptor the API transcribes, so
                # the provider's own text never duplicates the body.
                transcript = _item_text(item)
                if transcript:
                    texts.append(transcript)
            continue
        text = _item_text(item)
        if text:
            texts.append(text)
    text = "\n".join(texts)[:_TEXT_LIMIT]
    payload = {"peer": msg["from_user_id"], "message_id": str(msg["message_id"]),
               "context_token": msg.get("context_token"), "text": text,
               "media": media, "media_kind": media_kind, "media_name": media_name, "quote": quote}
    media_items = _media_items(items)
    if media_items:
        payload["media_items"] = media_items
    return payload


REFRESH_SECONDS = 30


class AccountUnavailable(Exception):
    """The API no longer serves this account; stop its poller."""


def env_config():
    api = os.environ.get("Y_AGENT_WECHAT_BRIDGE_API", "").strip().rstrip("/")
    key = os.environ.get("Y_AGENT_WECHAT_BRIDGE_KEY", "").strip()
    if urlsplit(api).scheme != "https" or not key:
        raise ValueError("Bridge requires an HTTPS API and a bridge key")
    return api, key


def account_entry(value):
    """One account's durable cursor, tolerating a pre-migration shape."""
    value = value if isinstance(value, dict) else {}
    receipts = value.get("sent_unacked")
    if not isinstance(receipts, dict):
        receipts = {str(key): None for key in receipts or []}
    return {"get_updates_buf": value.get("get_updates_buf") or "",
            "sent_unacked": receipts,
            "paused_until": value.get("paused_until") or 0}


def load_state(path):
    """Read the state, migrating the legacy single-account file in place."""
    try:
        state = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {"accounts": {}}
    accounts = state.get("accounts")
    if not isinstance(accounts, dict):
        account = state.get("ilink_bot_id")
        accounts = {account: account_entry(state)} if isinstance(account, str) and account else {}
    return {"accounts": {str(name): account_entry(value) for name, value in accounts.items()}}


def api_call(http, api, key, action, body=None, timeout=40):
    response = http.post(api + "/api/wechat/bridge/" + action, json=body or {},
                         headers={"Authorization": "Bearer " + key}, timeout=timeout)
    if response.status_code in (401, 403):
        raise ValueError("Bridge revoked or access denied")
    if response.status_code == 404:
        raise AccountUnavailable()
    response.raise_for_status()
    return response.json()


def drain(client, http, api, key, account, entry, path, state, lock):
    for _ in range(100):
        row = api_call(http, api, key, "claim", {"account": account})["item"]
        if not row:
            return
        receipts = entry["sent_unacked"]
        ok = row["outbox_id"] in receipts
        if not ok:
            try:
                provider_message_id = client.send(row)
            except ProviderError as exc:
                if exc.code == -14:
                    raise
            else:
                ok = True
                with lock:
                    receipts[row["outbox_id"]] = provider_message_id
                    save(path, state)
        ack = {"account": account, "outbox_id": row["outbox_id"], "lease": row["lease"], "ok": ok}
        if receipts.get(row["outbox_id"]):
            ack["provider_message_id"] = receipts[row["outbox_id"]]
        api_call(http, api, key, "ack", ack)
        if ok:
            with lock:
                receipts.pop(row["outbox_id"], None)
                save(path, state)


def account_loop(account, target, entry, path, state, lock, api, key, stop):
    started = False
    timeout = 35
    with httpx.Client(follow_redirects=False) as http:
        client = Client(http, target["base_url"], target["bot_token"])
        try:
            while not stop.is_set():
                try:
                    api_call(http, api, key, "heartbeat", {"account": account})
                    if time.time() < entry["paused_until"]:
                        stop.wait(REFRESH_SECONDS)
                        continue
                    if not started:
                        client.post("msg/notifystart", {})
                        started = True
                    drain(client, http, api, key, account, entry, path, state, lock)
                    batch = client.post("getupdates",
                                        {"get_updates_buf": entry["get_updates_buf"]}, timeout + 5)
                    for msg in batch.get("msgs") or []:
                        payload = inbound(msg, account)
                        if payload:
                            payload["account"] = account
                            # The API fetches and decrypts media inside this
                            # request; give it more than the default budget.
                            api_call(http, api, key, "inbound", payload, timeout=120)
                    if batch.get("get_updates_buf"):
                        with lock:
                            entry["get_updates_buf"] = batch["get_updates_buf"]
                            save(path, state)
                    api_call(http, api, key, "heartbeat", {"account": account, "polled": True})
                    timeout = min(120, max(1, (batch.get("longpolling_timeout_ms") or 35000) / 1000))
                except ProviderError as exc:
                    if exc.code == -14:
                        with lock:
                            entry["paused_until"] = time.time() + 3600
                            save(path, state)
                    stop.wait(3)
                except httpx.HTTPError:
                    stop.wait(3)
                except AccountUnavailable:
                    return
        finally:
            if started:
                with suppress(httpx.HTTPError, ProviderError):
                    client.post("msg/notifystop", {})


def run(path):
    api, key = env_config()
    with exclusive(path), httpx.Client(follow_redirects=False) as http:
        if path.exists() and path.stat().st_mode & 0o077:
            raise ValueError("Bridge requires private state and an HTTPS API")
        state = load_state(path)
        save(path, state)
        lock = threading.Lock()
        workers = {}
        try:
            while True:
                try:
                    listing = api_call(http, api, key, "accounts")["accounts"]
                except httpx.HTTPError:
                    time.sleep(REFRESH_SECONDS)
                    continue
                targets = {row["account"]: row for row in listing
                           if isinstance(row, dict) and row.get("account")}
                for account, worker in list(workers.items()):
                    target = targets.get(account)
                    if target is None or target != worker["target"] or not worker["thread"].is_alive():
                        worker["stop"].set()
                        del workers[account]
                for account, target in targets.items():
                    if account in workers:
                        continue
                    with lock:
                        entry = state["accounts"].setdefault(account, account_entry({}))
                        save(path, state)
                    stop = threading.Event()
                    thread = threading.Thread(
                        target=account_loop,
                        args=(account, target, entry, path, state, lock, api, key, stop),
                        daemon=True,
                    )
                    thread.start()
                    workers[account] = {"stop": stop, "thread": thread, "target": target}
                time.sleep(REFRESH_SECONDS)
        finally:
            for worker in workers.values():
                worker["stop"].set()
            for worker in workers.values():
                worker["thread"].join(timeout=10)
