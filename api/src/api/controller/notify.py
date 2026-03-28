from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from storage.service import chat as chat_service
from storage.entity.dto import Message
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

from storage.service.chat import send_chat_message

router = APIRouter(prefix="/notify")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class NotifyRequest(BaseModel):
    skill: str
    message: str
    work_dir: Optional[str] = None
    trace_id: Optional[str] = None
    from_skill: str
    force_new: Optional[bool] = False
    chat_id: Optional[str] = None
    from_chat_id: Optional[str] = None


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: Optional[str] = None


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Resolve target chat: explicit chat_id > skill+trace lookup > new
    existing_chat = None
    if req.chat_id:
        existing_chat = await chat_service.get_chat_by_id(req.chat_id)
        if not existing_chat:
            raise HTTPException(status_code=404, detail=f"chat_id '{req.chat_id}' not found")
        if existing_chat.skill and existing_chat.skill != req.skill:
            raise HTTPException(
                status_code=400,
                detail=f"skill mismatch: chat '{req.chat_id}' belongs to skill '{existing_chat.skill}', got '{req.skill}'"
            )
        chat_id = req.chat_id
    elif not req.force_new:
        from storage.repository.chat import find_chat_by_skill_and_trace, find_chat_by_skill
        found = None
        # DM skill doesn't have trace_id on its chats, so look up by skill only
        if req.skill == 'DM':
            found = find_chat_by_skill(user_id, req.skill)
        elif req.trace_id:
            found = find_chat_by_skill_and_trace(user_id, req.skill, req.trace_id)
        if found:
            chat_id = found.id
            existing_chat = await chat_service.get_chat_by_id(chat_id)
        else:
            chat_id = generate_id()
    else:
        chat_id = generate_id()

    # Build message content with trace metadata prefix
    from_chat_part = f' from_chat:{req.from_chat_id}' if req.from_chat_id else ''
    trace_part = f'trace:{req.trace_id} ' if req.trace_id else ''
    msg_content = f'[{trace_part}from:{req.from_skill} to:{req.skill}{from_chat_part} to_chat:{chat_id}]\n{req.message}'
    user_msg = Message.from_dict({
        "role": "user",
        "content": msg_content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })

    # Resolve work_dir and append/create chat
    work_dir = req.work_dir
    if existing_chat:
        if existing_chat.work_dir:
            if work_dir and work_dir != existing_chat.work_dir:
                raise HTTPException(status_code=400, detail=f"work_dir mismatch: chat has '{existing_chat.work_dir}', got '{work_dir}'")
            if not work_dir:
                work_dir = existing_chat.work_dir
        await chat_service.append_message(chat_id, user_msg)
    else:
        await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)

    # Short-circuit: DM callback messages get auto-ack without LLM
    if req.skill == 'DM':
        ack_content = "已收到"
        ack_msg = Message.from_dict({
            "role": "assistant",
            "content": ack_content,
            "timestamp": get_utc_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp(),
            "id": generate_message_id(),
        })
        await chat_service.append_message(chat_id, ack_msg)

        # Send both user message and ack to Telegram
        try:
            from storage.util import get_telegram_bot_token, send_telegram_message
            from storage.repository.user import get_user_by_id
            bot_token = get_telegram_bot_token()
            if bot_token:
                user = get_user_by_id(user_id)
                if user and user.telegram_id:
                    send_telegram_message(bot_token, user.telegram_id, msg_content)
                    send_telegram_message(bot_token, user.telegram_id, ack_content)
        except Exception as e:
            logger.exception("DM short-circuit telegram notify failed: {}", e)

        return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)

    # Enqueue worker
    send_chat_message(chat_id, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, skill=req.skill)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
