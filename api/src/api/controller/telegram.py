import base64
import os
from typing import List, Optional

import jwt
import httpx
from loguru import logger
from fastapi import APIRouter, Request

from storage.repository.user import get_user_by_telegram_id, bind_telegram_id, unbind_telegram_id
from storage.repository.chat import find_chat_by_channel_sync, save_chat as repo_save_chat
from storage.repository.tg_topic import get_topic_by_name
from storage.service.tg_topic import auto_discover_topic
from storage.entity.dto import Message
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp, markdown_to_telegram_html

router = APIRouter(prefix="/telegram")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_DEV", os.getenv("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"


def _bot_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def _resolve_topic_id(user_id: int, group_id: int, topic_name: str) -> Optional[int]:
    """Look up topic_id from DB by name."""
    topic = get_topic_by_name(user_id, group_id, topic_name)
    if topic and topic.topic_id is not None:
        return topic.topic_id
    return None


async def _send_message(chat_id, text: str, parse_mode: Optional[str] = "HTML", message_thread_id=None):
    """Send a message to a Telegram chat, splitting if too long."""
    if parse_mode == "HTML":
        text = markdown_to_telegram_html(text)
    MAX_LEN = 4096
    chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id
            resp = await client.post(_bot_api_url("sendMessage"), json=payload)
            # Retry without parse_mode if formatting fails
            if not resp.is_success and parse_mode:
                payload.pop("parse_mode")
                payload["text"] = chunk  # keep original chunk
                await client.post(_bot_api_url("sendMessage"), json=payload)


def _get_send_chat_message():
    """Import _send_chat_message from chat controller to reuse queue dispatch."""
    from api.controller.chat import _send_chat_message
    return _send_chat_message


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    # Verify the secret token set via setWebhook(secret_token=...)
    if not TELEGRAM_WEBHOOK_SECRET:
        logger.error("telegram webhook: TELEGRAM_WEBHOOK_SECRET not configured")
        return {"ok": False}
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if token != TELEGRAM_WEBHOOK_SECRET:
        logger.warning("telegram webhook: invalid secret token")
        return {"ok": False}

    body = await request.json()
    logger.info("telegram webhook body: {}", body)
    message = body.get("message")
    if not message:
        logger.info("telegram webhook: no message in body")
        return {"ok": True}

    telegram_chat_id = message["chat"]["id"]
    telegram_user_id = message["from"]["id"]
    message_thread_id = message.get("message_thread_id")
    text = message.get("text", "").strip()

    # Handle photo messages
    images = []
    if message.get("photo"):
        text = message.get("caption", "").strip() or "请看这张图片"
        images = await _download_telegram_photos(message["photo"])

    if not text:
        logger.info("telegram webhook: empty text")
        return {"ok": True}

    # Handle /bind command
    if text.startswith("/bind"):
        return await _handle_bind(telegram_chat_id, telegram_user_id, text, message_thread_id)

    # Handle /unbind command
    if text == "/unbind":
        return await _handle_unbind(telegram_chat_id, telegram_user_id, message_thread_id)

    # Handle /clear command — start a new session
    if text == "/clear":
        return await _handle_clear(telegram_chat_id, telegram_user_id, message_thread_id)

    # Handle /start command
    if text == "/start":
        await _send_message(
            telegram_chat_id,
            "Welcome to y-agent bot!\n\n"
            "Use /bind <jwt_token> to link your account.\n"
            "Use /unbind to unlink your account.\n"
            "Use /clear to start a new session.\n"
            "Send any text to chat.\n\n"
            "In forum groups, each topic is a separate chat session.",
            message_thread_id=message_thread_id,
        )
        return {"ok": True}

    # Regular message — route to chat
    return await _handle_message(telegram_chat_id, telegram_user_id, text, images=images, message_thread_id=message_thread_id)


async def _download_telegram_photos(photo_sizes: list) -> List[str]:
    """Download the largest photo from Telegram and return as base64 data URL list."""
    if not photo_sizes or not TELEGRAM_BOT_TOKEN:
        return []

    # Telegram sends multiple sizes; last is largest
    file_id = photo_sizes[-1]["file_id"]

    try:
        async with httpx.AsyncClient() as client:
            # Get file path
            resp = await client.get(_bot_api_url("getFile"), params={"file_id": file_id})
            if not resp.is_success:
                logger.error("telegram getFile failed: {}", resp.text)
                return []
            file_path = resp.json()["result"]["file_path"]

            # Download file
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            resp = await client.get(file_url)
            if not resp.is_success:
                logger.error("telegram file download failed: {}", resp.status_code)
                return []

            b64 = base64.b64encode(resp.content).decode("ascii")
            ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "jpg"
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
            return [f"data:{mime};base64,{b64}"]
    except Exception as e:
        logger.exception("telegram photo download error: {}", e)
        return []


async def _handle_bind(telegram_chat_id, telegram_user_id, text: str, message_thread_id=None):
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await _send_message(telegram_chat_id, "Usage: /bind <jwt_token>\n\nGet your token from the web app or CLI (y login).", message_thread_id=message_thread_id)
        return {"ok": True}

    token = parts[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        await _send_message(telegram_chat_id, "Invalid or expired token. Please get a fresh token from the web app or CLI.", message_thread_id=message_thread_id)
        return {"ok": True}

    email = payload.get("email", "")
    user = bind_telegram_id(email, telegram_user_id)
    if user:
        await _send_message(telegram_chat_id, f"Bound to account: {email}", message_thread_id=message_thread_id)
    else:
        await _send_message(telegram_chat_id, f"No account found for: {email}", message_thread_id=message_thread_id)
    return {"ok": True}


async def _handle_unbind(telegram_chat_id, telegram_user_id, message_thread_id=None):
    user = unbind_telegram_id(telegram_user_id)
    if user:
        await _send_message(telegram_chat_id, f"Unbound account: {user.email}", message_thread_id=message_thread_id)
    else:
        await _send_message(telegram_chat_id, "No account is bound to this Telegram user.", message_thread_id=message_thread_id)
    return {"ok": True}


async def _handle_clear(telegram_chat_id, telegram_user_id, message_thread_id=None):
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        await _send_message(telegram_chat_id, "Please /bind your account first.", message_thread_id=message_thread_id)
        return {"ok": True}

    channel_id = f"telegram:{telegram_chat_id}"
    if message_thread_id:
        channel_id = f"telegram:{telegram_chat_id}:{message_thread_id}"

    # Create a new empty chat with the same channel_id, replacing the current session
    chat_id = generate_id()
    from storage.dto.chat import Chat as ChatDTO
    timestamp = get_utc_iso8601_timestamp()
    chat = ChatDTO(
        id=chat_id,
        create_time=timestamp,
        update_time=timestamp,
        messages=[],
        channel_id=channel_id,
    )
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat(user.id, chat)

    await _send_message(telegram_chat_id, "New session started.", message_thread_id=message_thread_id)
    return {"ok": True}


async def _handle_message(telegram_chat_id, telegram_user_id, text: str, images: Optional[List[str]] = None, message_thread_id=None):
    logger.info("_handle_message: telegram_chat_id={} telegram_user_id={} text={} images={} thread={}", telegram_chat_id, telegram_user_id, text, len(images) if images else 0, message_thread_id)
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        logger.info("_handle_message: no user bound for telegram_user_id={}", telegram_user_id)
        await _send_message(telegram_chat_id, "Please /bind your account first.", message_thread_id=message_thread_id)
        return {"ok": True}

    logger.info("_handle_message: found user id={} email={}", user.id, user.email)

    # Auto-discover forum topic in DB
    if message_thread_id:
        try:
            auto_discover_topic(user.id, telegram_chat_id, message_thread_id)
        except Exception as e:
            logger.warning("tg_topic auto-discover failed: {}", e)

    # Each forum topic (message_thread_id) maps to a separate chat session
    channel_id = f"telegram:{telegram_chat_id}"
    if message_thread_id:
        channel_id = f"telegram:{telegram_chat_id}:{message_thread_id}"

    # Find or create chat for this channel
    chat = find_chat_by_channel_sync(user.id, channel_id)
    logger.info("_handle_message: existing chat={}", chat.id if chat else None)
    if chat:
        # Append message to existing chat
        msg_dict = {
            "role": "user",
            "content": text,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        }
        if images:
            msg_dict["images"] = images
        user_msg = Message.from_dict(msg_dict)
        chat.messages.append(user_msg)
        chat.interrupted = False
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat_by_id(chat)
        chat_id = chat.id
    else:
        # Create new chat
        chat_id = generate_id()
        msg_dict = {
            "role": "user",
            "content": text,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        }
        if images:
            msg_dict["images"] = images
        user_msg = Message.from_dict(msg_dict)
        from storage.dto.chat import Chat as ChatDTO
        timestamp = get_utc_iso8601_timestamp()
        chat = ChatDTO(
            id=chat_id,
            create_time=timestamp,
            update_time=timestamp,
            messages=[user_msg],
            channel_id=channel_id,
        )
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat(user.id, chat)

    # Queue for processing with telegram_reply post-hook
    try:
        send_chat_message = _get_send_chat_message()
        send_chat_message(
            chat_id,
            user_id=user.id,
            post_hooks=[{"type": "telegram_reply", "telegram_chat_id": telegram_chat_id, "message_thread_id": message_thread_id}],
        )
    except Exception as e:
        logger.exception("_handle_message: failed to queue message: {}", e)
    return {"ok": True}
