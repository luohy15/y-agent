import os
import logging
from typing import Optional

import jwt
import httpx
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

from storage.repository.user import get_user_by_telegram_id, bind_telegram_id, unbind_telegram_id
from storage.repository.chat import find_chat_by_channel_sync, save_chat as repo_save_chat
from storage.entity.dto import Message
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

router = APIRouter(prefix="/telegram")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"


def _bot_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


async def _send_message(chat_id: int, text: str, parse_mode: Optional[str] = "Markdown"):
    """Send a message to a Telegram chat, splitting if too long."""
    MAX_LEN = 4096
    chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = await client.post(_bot_api_url("sendMessage"), json=payload)
            # Retry without parse_mode if markdown fails
            if not resp.is_success and parse_mode:
                payload.pop("parse_mode")
                await client.post(_bot_api_url("sendMessage"), json=payload)


def _get_send_chat_message():
    """Import _send_chat_message from chat controller to reuse queue dispatch."""
    from api.controller.chat import _send_chat_message
    return _send_chat_message


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    body = await request.json()
    logger.info("telegram webhook body: %s", body)
    message = body.get("message")
    if not message:
        logger.info("telegram webhook: no message in body")
        return {"ok": True}

    telegram_chat_id = message["chat"]["id"]
    telegram_user_id = message["from"]["id"]
    text = message.get("text", "").strip()

    if not text:
        logger.info("telegram webhook: empty text")
        return {"ok": True}

    # Handle /bind command
    if text.startswith("/bind"):
        return await _handle_bind(telegram_chat_id, telegram_user_id, text)

    # Handle /unbind command
    if text == "/unbind":
        return await _handle_unbind(telegram_chat_id, telegram_user_id)

    # Handle /new command
    if text == "/new":
        return await _handle_new(telegram_chat_id, telegram_user_id)

    # Handle /start command
    if text == "/start":
        await _send_message(
            telegram_chat_id,
            "Welcome to y-agent bot!\n\n"
            "Use /bind <jwt_token> to link your account.\n"
            "Use /unbind to unlink your account.\n"
            "Use /new to start a new chat.\n"
            "Send any text to chat.",
        )
        return {"ok": True}

    # Regular message — route to chat
    return await _handle_message(telegram_chat_id, telegram_user_id, text)


async def _handle_bind(telegram_chat_id: int, telegram_user_id: int, text: str):
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await _send_message(telegram_chat_id, "Usage: /bind <jwt_token>\n\nGet your token from the web app or CLI (y login).")
        return {"ok": True}

    token = parts[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        await _send_message(telegram_chat_id, "Invalid or expired token. Please get a fresh token from the web app or CLI.")
        return {"ok": True}

    email = payload.get("email", "")
    user = bind_telegram_id(email, telegram_user_id)
    if user:
        await _send_message(telegram_chat_id, f"Bound to account: {email}")
    else:
        await _send_message(telegram_chat_id, f"No account found for: {email}")
    return {"ok": True}


async def _handle_unbind(telegram_chat_id: int, telegram_user_id: int):
    user = unbind_telegram_id(telegram_user_id)
    if user:
        await _send_message(telegram_chat_id, f"Unbound account: {user.email}")
    else:
        await _send_message(telegram_chat_id, "No account is bound to this Telegram user.")
    return {"ok": True}


async def _handle_new(telegram_chat_id: int, telegram_user_id: int):
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        await _send_message(telegram_chat_id, "Please /bind your account first.")
        return {"ok": True}

    channel_id = f"telegram:{telegram_chat_id}"
    chat_id = generate_id()

    # Create empty chat with channel_id
    from storage.dto.chat import Chat
    timestamp = get_utc_iso8601_timestamp()
    chat = Chat(
        id=chat_id,
        create_time=timestamp,
        update_time=timestamp,
        messages=[],
        channel_id=channel_id,
    )
    await repo_save_chat(user.id, chat)

    await _send_message(telegram_chat_id, "New chat started.")
    return {"ok": True}


async def _handle_message(telegram_chat_id: int, telegram_user_id: int, text: str):
    logger.info("_handle_message: telegram_chat_id=%s telegram_user_id=%s text=%s", telegram_chat_id, telegram_user_id, text)
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        logger.info("_handle_message: no user bound for telegram_user_id=%s", telegram_user_id)
        await _send_message(telegram_chat_id, "Please /bind your account first.")
        return {"ok": True}

    logger.info("_handle_message: found user id=%s email=%s", user.id, user.email)
    channel_id = f"telegram:{telegram_chat_id}"

    # Find or create chat for this channel
    chat = find_chat_by_channel_sync(user.id, channel_id)
    logger.info("_handle_message: existing chat=%s", chat.id if chat else None)
    if chat:
        # Append message to existing chat
        user_msg = Message.from_dict({
            "role": "user",
            "content": text,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        })
        chat.messages.append(user_msg)
        chat.interrupted = False
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat_by_id(chat)
        chat_id = chat.id
    else:
        # Create new chat
        chat_id = generate_id()
        user_msg = Message.from_dict({
            "role": "user",
            "content": text,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        })
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
    logger.info("_handle_message: queuing chat_id=%s user_id=%s to SQS", chat_id, user.id)
    try:
        send_chat_message = _get_send_chat_message()
        send_chat_message(
            chat_id,
            user_id=user.id,
            post_hooks=[{"type": "telegram_reply", "telegram_chat_id": telegram_chat_id}],
        )
        logger.info("_handle_message: queued successfully")
    except Exception as e:
        logger.exception("_handle_message: failed to queue message: %s", e)
    return {"ok": True}
