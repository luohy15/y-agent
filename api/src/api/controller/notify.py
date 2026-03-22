from typing import Optional

from fastapi import APIRouter, Query, Request
from loguru import logger
from pydantic import BaseModel

from storage.service import chat as chat_service
from storage.entity.dto import Message
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

from api.controller.chat import _send_chat_message

router = APIRouter(prefix="/notify")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class NotifyRequest(BaseModel):
    skill: str
    message: str
    work_dir: Optional[str] = None
    trace_id: str
    from_skill: str
    force_new: Optional[bool] = False


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: str


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Build message content with meta-info line + skill command
    if req.skill == 'DM':
        msg_content = f'[trace:{req.trace_id} from:{req.from_skill}]\n{req.message}'
    else:
        msg_content = f'[trace:{req.trace_id} from:{req.from_skill}]\n/{req.skill} {req.message}'
    user_msg = Message.from_dict({
        "role": "user",
        "content": msg_content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
        "trace_id": req.trace_id,
    })

    # Find existing chat to resume: match by skill + active_trace_id.
    # If no match, create a new chat.
    chat_id = None
    if not req.force_new:
        from storage.repository.chat import find_chat_by_skill_and_trace
        existing = find_chat_by_skill_and_trace(user_id, req.skill, req.trace_id)
        if existing:
            chat_id = existing.id

    if chat_id:
        await chat_service.append_message(chat_id, user_msg)
    else:
        # Priority 3: create new chat
        chat_id = generate_id()
        await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)

    # Enqueue worker (bot_name = skill name, pass trace context via queue)
    _send_chat_message(chat_id, user_id=user_id, work_dir=req.work_dir, trace_id=req.trace_id, skill=req.skill)

    # Send Telegram notification to the target skill's topic
    await _notify_telegram_topic(user_id, req, chat_id)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)


async def _notify_telegram_topic(user_id: int, req: NotifyRequest, chat_id: str) -> None:
    """Send a notification to the Telegram topic matching the target skill name,
    then update the chat's channel_id so Telegram replies route to this chat.
    For DM skill, send as a private message to the user's telegram_id."""
    try:
        from storage.util import get_telegram_bot_token
        bot_token = get_telegram_bot_token()
        if not bot_token:
            logger.warning("notify telegram: TELEGRAM_BOT_TOKEN not set")
            return

        if req.skill == 'DM':
            text = f"[trace:{req.trace_id} from:{req.from_skill}]\n{req.message}"
        else:
            text = f"[trace:{req.trace_id} from:{req.from_skill}]\n/{req.skill} {req.message}"

        from api.controller.telegram import _send_message
        from storage.repository.chat import update_channel_id

        if req.skill == 'DM':
            # Send as private message to user's telegram_id
            from storage.repository.user import get_user_by_id
            user = get_user_by_id(user_id)
            if not user or not user.telegram_id:
                logger.debug("notify telegram DM: no telegram_id for user_id={}", user_id)
                return

            telegram_id = user.telegram_id
            await _send_message(telegram_id, text, message_thread_id=None)
            logger.info("notify telegram DM: sent to telegram_id={}", telegram_id)

            channel_id = f"telegram:{telegram_id}"
            update_channel_id(user_id, chat_id, channel_id)
            logger.info("notify telegram: updated channel_id='{}' on chat_id='{}'", channel_id, chat_id)
        else:
            from storage.repository.tg_topic import find_topic_by_name

            topic = find_topic_by_name(user_id, req.skill)
            if not topic or topic.topic_id is None:
                logger.debug("notify telegram: no topic found for skill '{}'", req.skill)
                return

            await _send_message(topic.group_id, text, message_thread_id=topic.topic_id)
            logger.info("notify telegram: sent to skill='{}' group={} topic={}", req.skill, topic.group_id, topic.topic_id)

            channel_id = f"telegram:{topic.group_id}:{topic.topic_id}"
            update_channel_id(user_id, chat_id, channel_id)
            logger.info("notify telegram: updated channel_id='{}' on chat_id='{}'", channel_id, chat_id)
    except Exception as e:
        logger.exception("notify telegram failed: {}", e)
