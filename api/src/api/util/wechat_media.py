"""Inbound WeChat image/file handling for the shared gateway path.

The bridge forwards a small CDN descriptor. This module applies the target
node and backend guards, then per item fetches and decrypts through
`storage.service.wechat_media`, normalizes and stores an image, classifies and
stores a file, and returns one user-visible notice per rejection.
"""

from loguru import logger

from api.util.attachments import classify_document, save_attachment_bytes
from api.util.images import ImageRejected, normalize_image_bytes, save_image_bytes
from storage.service.wechat_media import (
    MAX_FILE_BYTES, MAX_IMAGE_BYTES, MediaRejected, fetch_media,
)

AGY_BACKEND = "agy"
IMAGE = "image"
FILE = "file"


def _reject_notice(kind, code):
    if code == "too_large":
        if kind == IMAGE:
            return "That image is larger than 10 MB, so it was not saved."
        return "That file is larger than 20 MB, so it was not saved."
    if code == "unsupported_type":
        if kind == IMAGE:
            return "That image type is not supported."
        return "That file type is not supported."
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


async def handle_media(*, user_id, chat, items):
    """Return `(image_paths, file_paths, notices)` for one inbound message."""
    images, files, notices = [], [], []
    if not items:
        return images, files, notices
    block = _node_block(user_id, chat)
    if block:
        return images, files, [block]
    images_refused = getattr(chat, "backend", None) == AGY_BACKEND
    for item in items:
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind == IMAGE:
            if images_refused:
                notices.append("Images are not supported in this conversation.")
                continue
            try:
                data = await fetch_media(item, max_bytes=MAX_IMAGE_BYTES)
                content, suffix = normalize_image_bytes(data)
                images.append(_save_image(content, suffix, user_id))
            except (MediaRejected, ImageRejected) as exc:
                notices.append(_reject_notice(IMAGE, exc.code))
            except Exception:
                logger.exception("wechat inbound image failed")
                notices.append(_store_notice(IMAGE))
        elif kind == FILE:
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
            except Exception:
                logger.exception("wechat inbound file failed")
                notices.append(_store_notice(FILE))
        else:
            notices.append("That attachment type is not supported.")
    return images, files, notices
