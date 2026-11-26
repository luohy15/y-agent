"""Shared inbound voice transcription for the gateway channels (todo 4484).

WeChat and Telegram both drop a descriptor here, not an audio file: the
channel's own fetcher (WeChat CDN decrypt, Telegram getFile) returns the raw
bytes, this module decodes them to 16 kHz mono PCM16, and uploads them to the
published `voice` module in-process as the sending peer's own user. The module
owns the take row, transcription and polish, so both channels share one
quality and archive path.

Every rejection is a closed `VoiceRejected` code that the channel turns into
one explicit user-visible notice (`voice_notice`). Pre-checks run before the
download, so an unsupported route or account never fetches audio.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import uuid

from loguru import logger

from api.util.voice_transcode import (
    MAX_VOICE_BYTES,
    VoiceRejected,
    part_offsets,
    transcode,
)

MODULE_SLUG = "voice"
_TOTAL_TIMEOUT = 45.0
_CANCEL_TIMEOUT = 5.0
_MAX_RESPONSE_BYTES = 64 * 1024
_CHANNELS = {"wechat": "WeChat", "telegram": "Telegram"}

_NOTICES = {
    "too_large": "That voice message is larger than 4 MB, so it was not transcribed.",
    "too_long": "That voice message is longer than 2 minutes, so it was not transcribed.",
    "unsupported_type": "That voice format is not supported. Send a voice message or text instead.",
    "not_configured": "Voice transcription is not configured on the server.",
    "forbidden": "Voice input is not enabled for this account.",
    "empty_transcript": "I could not hear any speech in that voice message.",
    "timeout": "Transcribing that voice message took too long, so it was not delivered.",
    "unavailable": "Could not transcribe that voice message.",
    "node_blocked": "Voice input is not supported in this conversation.",
}


def voice_notice(code, channel=None):
    """One user-visible notice for a closed rejection code, never empty."""
    if code == "download_failed":
        return f"Could not download that voice message from {_CHANNELS.get(channel, 'the chat')}."
    return _NOTICES.get(code) or "Could not process that voice message."


async def process_inbound_voice(
    *, user_id, chat, fetch, duration_ms=None, label, channel=None,
):
    """Transcribe one inbound voice note and return its text.

    `fetch(max_bytes)` is the channel's downloader and returns decrypted bytes.
    Everything that can be judged without the audio is checked first.
    """
    _precheck(user_id, chat, duration_ms)
    try:
        data = await fetch(max_bytes=MAX_VOICE_BYTES)
    except VoiceRejected:
        raise
    except Exception as exc:
        # loguru's default diagnose=True dumps frame locals: never log the
        # fetch closure, descriptor or exception, which carry CDN URLs/keys.
        logger.error("inbound voice download failed: {}", type(exc).__name__)
        raise VoiceRejected("download_failed") from None
    pcm, decoded_ms = await asyncio.to_thread(transcode, data)
    return await _transcribe(user_id, pcm, decoded_ms, label)


def _precheck(user_id, chat, duration_ms):
    if type(duration_ms) is int and duration_ms > 0:
        from api.util.voice_transcode import MAX_DURATION_MS

        if duration_ms > MAX_DURATION_MS:
            raise VoiceRejected("too_long")
    _require_node(user_id, chat)
    _require_module(user_id)
    if not os.environ.get("OPENROUTER_INFERENCE_API_KEY", "").strip():
        raise VoiceRejected("not_configured")


def _require_node(user_id, chat):
    from agent.chat_target import ChatTargetUnavailable, UnknownChatTarget, layout

    try:
        layout(user_id, getattr(chat, "execution_target", None), use_cache=False)
    except (UnknownChatTarget, ChatTargetUnavailable) as exc:
        logger.info("inbound voice rejected: node unavailable ({})", exc)
        raise VoiceRejected("node_blocked") from None


def _require_module(user_id):
    from api.controller.module import default_owner_user_id
    from api.module_runtime import loader
    from api.module_runtime.errors import ModuleDisabledError

    try:
        owner = default_owner_user_id()
        if owner is None:
            raise VoiceRejected("forbidden")
        version = loader.resolve_active_version(owner, MODULE_SLUG)
    except VoiceRejected:
        raise
    except ModuleDisabledError:
        # The dispatcher answers 403 for a disabled module; keep the notice
        # identical and stay quiet instead of logging a scary traceback.
        raise VoiceRejected("forbidden") from None
    except Exception as exc:
        logger.error("inbound voice rejected: voice module is unavailable ({})",
                     type(exc).__name__)
        raise VoiceRejected("unavailable") from None
    if user_id != owner and version.dispatch_scope != "authenticated":
        raise VoiceRejected("forbidden")


async def _transcribe(user_id, pcm, duration_ms, label):
    take_id = str(uuid.uuid4())
    recorded_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    try:
        result = await asyncio.wait_for(
            _upload(user_id, take_id, pcm, duration_ms, recorded_at, label),
            _TOTAL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await _cancel(user_id, take_id)
        raise VoiceRejected("timeout") from None
    if result.get("status") == "transcribed":
        text = result.get("polished_text") or result.get("raw_text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        raise VoiceRejected("empty_transcript")
    if result.get("error") == "not_configured":
        raise VoiceRejected("not_configured")
    if result.get("error") == "empty_transcript":
        raise VoiceRejected("empty_transcript")
    raise VoiceRejected("unavailable")


async def _upload(user_id, take_id, pcm, duration_ms, recorded_at, label):
    parts = part_offsets(pcm)
    try:
        for index, offset, chunk in parts:
            status, _raw = await _call(
                user_id, "PUT", f"/takes/{take_id}/chunks/{index}",
                query=f"offset={offset}", content_type="audio/pcm", body=chunk,
            )
            if status != 200:
                raise VoiceRejected(_status_code(status))
        body = json.dumps({
            "audio_format": "pcm",
            "part_count": len(parts),
            "duration_ms": duration_ms,
            "recorded_at": recorded_at,
            "label": label,
        }).encode()
        status, raw = await _call(
            user_id, "POST", f"/takes/{take_id}/finalize",
            content_type="application/json", body=body,
        )
        if status != 200:
            raise VoiceRejected(_status_code(status))
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise VoiceRejected("unavailable")
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        await _cancel(user_id, take_id)
        raise


async def _cancel(user_id, take_id):
    try:
        await asyncio.wait_for(
            _call(user_id, "POST", f"/takes/{take_id}/cancel"),
            _CANCEL_TIMEOUT,
        )
    except Exception:
        logger.info("inbound voice cancel did not complete take_id={}", take_id)


def _status_code(status):
    if status == 403:
        return "forbidden"
    if status == 413:
        return "too_large"
    return "unavailable"


class _Collector:
    def __init__(self):
        self.status = 0
        self.body = bytearray()

    async def send(self, message):
        if message["type"] == "http.response.start":
            self.status = message["status"]
        elif message["type"] == "http.response.body":
            chunk = message.get("body") or b""
            if len(self.body) + len(chunk) > _MAX_RESPONSE_BYTES:
                raise ValueError("voice module response is too large")
            self.body.extend(chunk)


async def _call(user_id, method, path, *, query="", content_type=None, body=b""):
    """One in-process ASGI call into the published voice module as `user_id`."""
    from api.module_runtime.dispatcher import module_dispatcher

    headers = [(b"content-length", str(len(body)).encode("ascii"))]
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": f"/api/module/{MODULE_SLUG}{path}",
        "raw_path": f"/api/module/{MODULE_SLUG}{path}".encode(),
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 0),
        "state": {"user_id": user_id},
    }
    collector = _Collector()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    await module_dispatcher(scope, receive, collector.send)
    return collector.status, bytes(collector.body)
