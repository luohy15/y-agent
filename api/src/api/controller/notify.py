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

    # Get or create trace
    trace = trace_service.get_trace(user_id, req.trace_id)
    if trace is None:
        trace = Trace(trace_id=req.trace_id)

    # Register from_* as participant if provided
    if req.from_skill and req.from_chat_id:
        existing_from = next((p for p in trace.participants if p.skill == req.from_skill and p.chat_id == req.from_chat_id), None)
        if existing_from is None:
            trace.participants.append(TraceParticipant(
                chat_id=req.from_chat_id,
                skill=req.from_skill,
                work_dir=req.from_work_dir,
            ))

    # Find existing participant for target skill
    target_participant = next((p for p in trace.participants if p.skill == req.skill), None)

    chat_id = None
    if target_participant and not req.new_chat:
        # Append message to existing chat
        chat_id = target_participant.chat_id
        user_msg = Message.from_dict({
            "role": "user",
            "content": f'/{req.skill} {req.message}',
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        })
        await chat_service.append_message(chat_id, user_msg)
    else:
        # Create new chat
        chat_id = generate_id()
        user_msg = Message.from_dict({
            "role": "user",
            "content": f'/{req.skill} {req.message}',
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        })
        await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)

        # Register or update participant
        if target_participant:
            target_participant.chat_id = chat_id
            target_participant.work_dir = req.work_dir
        else:
            trace.participants.append(TraceParticipant(
                chat_id=chat_id,
                skill=req.skill,
                work_dir=req.work_dir,
            ))

    # Save trace
    trace_service.save_trace(user_id, trace)

    # Enqueue worker (bot_name = skill name)
    _send_chat_message(chat_id, bot_name=req.skill, user_id=user_id, work_dir=req.work_dir)

    # Send Telegram notification to the target skill's topic
    await _notify_telegram_topic(user_id, req)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)


async def _notify_telegram_topic(user_id: int, req: NotifyRequest) -> None:
    """Send a notification to the Telegram topic matching the target skill name."""
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
    except Exception as e:
        logger.exception("notify telegram failed: {}", e)
