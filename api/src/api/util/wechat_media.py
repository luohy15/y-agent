"""Inbound WeChat image/file/voice handling for the shared gateway path.

The bridge forwards a small CDN descriptor. This module applies the target
node and backend guards, then per item fetches and decrypts through
`storage.service.wechat_media`, normalizes and stores an image, classifies and
stores a file, or transcribes a voice note through the shared gateway voice
service, and returns one user-visible notice per rejection.
"""

from loguru import logger

from api.util import gateway_voice
from api.util.attachments import classify_document, save_attachment_bytes
from api.util.images import ImageRejected, normalize_image_bytes, save_image_bytes
from api.util.voice_transcode import VoiceRejected
from storage.service.wechat_media import (
    MAX_FILE_BYTES, MAX_IMAGE_BYTES, MAX_VOICE_BYTES, MediaRejected, fetch_media,
)

AGY_BACKEND = "agy"
IMAGE = "image"
FILE = "file"
VOICE = "voice"
_VOICE_READ_TIMEOUT = 20


def _reject_notice(kind, code):
    if code == "too_large":
        if kind == IMAGE:
            return "That image is larger than 10 MB, so it was not saved."
        return "That file is larger than 20 MB, so it was not saved."
    if code == "unsupported_type":
        return "That image type is not supported."
    return f"Could not download that {kind} from WeChat. Nothing was saved."


def _store_notice(kind):
    return f"Could not save that {kind}."


def _node_block(user_id, chat):
    """One notice when this target's node cannot read stored media, else None."""
    from agent.chat_target import ChatTargetUnavailable, UnknownChatTarget, layout

    try:
        node = layout(user_id, getattr(chat, "execution_target", None), use_cache=False)
    except (UnknownChatTarget, ChatTargetUnavailable) as exc:
        return f"Images and files are not supported: {exc}"
    if not node.supports_images:
        return (f"Images and files are not supported on node '{node.name}'. "
                "That node cannot read the stored file.")
    return None


def _save_image(content, suffix, user_id):
    from agent.config import resolve_vm_config

    return save_image_bytes(
        content, prefix="wechat", suffix=suffix, vm_config=resolve_vm_config(user_id),
    )


def _save_file(content, filename, user_id):
    from agent.config import resolve_vm_config

    return save_attachment_bytes(
        content, filename, prefix="wechat", vm_config=resolve_vm_config(user_id),
    )


def _voice_fetch(item):
    async def fetch(max_bytes):
        try:
            return await fetch_media(
                item, max_bytes=min(max_bytes, MAX_VOICE_BYTES),
                read_timeout=_VOICE_READ_TIMEOUT,
            )
        except MediaRejected as exc:
            raise VoiceRejected("too_large" if exc.code == "too_large" else "download_failed") from None

    return fetch


async def handle_media(*, user_id, chat, items):
    """Return `(image_paths, file_paths, transcript, notices)` for one message.

    Voice is plain text and needs no EC2 disk asset, so a jump node or an
    `agy` chat accepts it even though it still refuses images.
    """
    images, files, notices = [], [], []
    transcripts = []
    if not items:
        return images, files, None, notices
    block = _node_block(user_id, chat)
    images_refused = getattr(chat, "backend", None) == AGY_BACKEND
    for item in items:
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind == IMAGE:
            if block or images_refused:
                notice = "Images are not supported in this conversation." if images_refused else block
                if notice not in notices:
                    notices.append(notice)
                continue
            try:
                data = await fetch_media(item, max_bytes=MAX_IMAGE_BYTES)
                content, suffix = normalize_image_bytes(data)
                images.append(_save_image(content, suffix, user_id))
            except (MediaRejected, ImageRejected) as exc:
                notices.append(_reject_notice(IMAGE, exc.code))
            except Exception as exc:
                # loguru diagnose=True dumps locals (the descriptor carries CDN
                # URLs and AES keys); log only the exception type.
                logger.error("wechat inbound image failed: {}", type(exc).__name__)
                notices.append(_store_notice(IMAGE))
        elif kind == FILE:
            if block:
                if block not in notices:
                    notices.append(block)
                continue
            code = classify_document(
                {"file_name": item.get("file_name") or "", "file_size": item.get("size")})
            if code:
                notices.append(_reject_notice(FILE, code))
                continue
            try:
                data = await fetch_media(item, max_bytes=MAX_FILE_BYTES)
                files.append(_save_file(data, item.get("file_name") or "file", user_id))
            except MediaRejected as exc:
                notices.append(_reject_notice(FILE, exc.code))
            except Exception as exc:
                logger.error("wechat inbound file failed: {}", type(exc).__name__)
                notices.append(_store_notice(FILE))
        elif kind == VOICE:
            try:
                transcript = await gateway_voice.process_inbound_voice(
                    user_id=user_id, chat=chat, fetch=_voice_fetch(item),
                    duration_ms=item.get("duration_ms"), label="wechat", channel="wechat",
                )
            except VoiceRejected as exc:
                notices.append(gateway_voice.voice_notice(exc.code, "wechat"))
            except Exception as exc:
                logger.error("wechat inbound voice failed: {}", type(exc).__name__)
                notices.append(gateway_voice.voice_notice("unavailable", "wechat"))
            else:
                transcripts.append(transcript)
        else:
            notices.append("That attachment type is not supported.")
    return images, files, "\n".join(transcripts) or None, notices
