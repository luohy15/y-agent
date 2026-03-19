import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from loguru import logger
from pydantic import BaseModel

from storage.service import chat as chat_service
from storage.service import trace as trace_service
from storage.dto.trace import Trace, TraceParticipant
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
    from_chat_id: Optional[str] = None
    from_work_dir: Optional[str] = None
    from_skill: Optional[str] = None
    new_chat: Optional[bool] = False


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: str


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Get or create trace (notify is where a trace starts)
    trace = trace_service.get_trace(user_id, req.trace_id)
    if trace is None:
        trace = Trace(trace_id=req.trace_id)
        # Register the caller as the first participant (trace origin)
        if req.from_skill and req.from_chat_id:
            caller_chat = await chat_service.get_chat(user_id, req.from_chat_id)
            message_id = caller_chat.messages[-1].id if caller_chat and caller_chat.messages else None
            work_dir = caller_chat.work_dir if caller_chat else None
            trace.participants.append(TraceParticipant(
                chat_id=req.from_chat_id,
                skill=req.from_skill,
                work_dir=work_dir,
                message_id=message_id,
            ))
        trace_service.save_trace(user_id, trace)

    # Build message content (trace context is passed via env vars, not message)
    msg_content = f'/{req.skill} {req.message}'
    user_msg = Message.from_dict({
        "role": "user",
        "content": msg_content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })

    # Find existing chat_id with 3-tier priority:
    # 1. trace participant (skill already registered in this trace)
    # 2. skill's telegram topic channel (most recent chat for this skill)
    # 3. create new chat
    chat_id = None
    if not req.new_chat:
        # Priority 1: trace participant
        target_participant = next((p for p in trace.participants if p.skill == req.skill), None)
        if target_participant:
            chat_id = target_participant.chat_id

        # Priority 2: find by skill's telegram topic channel
        if not chat_id:
            try:
                from storage.repository.tg_topic import find_topic_by_name
                from storage.repository.chat import find_chat_by_channel_sync
                topic = find_topic_by_name(user_id, req.skill)
                if topic and topic.topic_id is not None:
                    channel_id = f"telegram:{topic.group_id}:{topic.topic_id}"
                    existing_chat = find_chat_by_channel_sync(user_id, channel_id)
                    if existing_chat:
                        chat_id = existing_chat.id
            except Exception as e:
                logger.warning("notify: skill channel lookup failed: {}", e)

    if chat_id:
        await chat_service.append_message(chat_id, user_msg)
    else:
        # Priority 3: create new chat
        chat_id = generate_id()
        await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)

    # Enqueue worker (bot_name = skill name, pass trace context via queue)
    _send_chat_message(chat_id, bot_name=req.skill, user_id=user_id, work_dir=req.work_dir, trace_id=req.trace_id, skill=req.skill)

    # Send Telegram notification to the target skill's topic
    await _notify_telegram_topic(user_id, req, chat_id)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)


async def _notify_telegram_topic(user_id: int, req: NotifyRequest, chat_id: str) -> None:
    """Send a notification to the Telegram topic matching the target skill name,
    then update the chat's channel_id so Telegram replies route to this chat."""
    try:
        from storage.repository.tg_topic import find_topic_by_name

        topic = find_topic_by_name(user_id, req.skill)
        if not topic or topic.topic_id is None:
            logger.debug("notify telegram: no topic found for skill '{}'", req.skill)
            return

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN_DEV", os.getenv("TELEGRAM_BOT_TOKEN", ""))
        if not bot_token:
            logger.warning("notify telegram: TELEGRAM_BOT_TOKEN not set")
            return

        from_label = req.from_skill or "unknown"
        text = f"📨 {from_label} → {req.skill}\n\n{req.message}"

        from api.controller.telegram import _send_message
        await _send_message(topic.group_id, text, message_thread_id=topic.topic_id)
        logger.info("notify telegram: sent to skill='{}' group={} topic={}", req.skill, topic.group_id, topic.topic_id)

        # Update channel_id on the target chat so Telegram replies go to this chat
        channel_id = f"telegram:{topic.group_id}:{topic.topic_id}"
        from storage.repository.chat import update_channel_id
        update_channel_id(user_id, chat_id, channel_id)
        logger.info("notify telegram: updated channel_id='{}' on chat_id='{}'", channel_id, chat_id)
    except Exception as e:
        logger.exception("notify telegram failed: {}", e)
