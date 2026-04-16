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
    topic: str
    message: str
    work_dir: Optional[str] = None
    trace_id: Optional[str] = None
    from_topic: str
    force_new: Optional[bool] = False
    chat_id: Optional[str] = None
    from_chat_id: Optional[str] = None
    backend: Optional[str] = None


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: Optional[str] = None


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Derive role from topic: "manager" is special, everything else is "worker"
    role = "manager" if req.topic == "manager" else "worker"

    # Manager does not accept notify callbacks (messages to existing chats),
    # but --new (force_new) is allowed to create a fresh manager session
    if role == 'manager' and not req.force_new:
        raise HTTPException(status_code=400, detail="Manager does not accept notify callbacks. Use --new to start a new manager session, or send to a specific topic instead.")

    # Resolve target chat: explicit chat_id > topic+trace lookup > new
    existing_chat = None
    if req.chat_id:
        existing_chat = await chat_service.get_chat_by_id(req.chat_id)
        if not existing_chat:
            raise HTTPException(status_code=404, detail=f"chat_id '{req.chat_id}' not found")
        if existing_chat.topic and existing_chat.topic != req.topic:
            raise HTTPException(
                status_code=400,
                detail=f"topic mismatch: chat '{req.chat_id}' belongs to topic '{existing_chat.topic}', got '{req.topic}'. Use --new to create a new chat, or omit --chat-id to let the system find the right one."
            )
        chat_id = req.chat_id
    elif not req.force_new:
        from storage.repository.chat import find_chat_by_topic_and_trace
        found = None
        if req.trace_id:
            found = find_chat_by_topic_and_trace(user_id, req.topic, req.trace_id)
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
    msg_content = f'[{trace_part}from:{req.from_topic} to:{req.topic}{from_chat_part} to_chat:{chat_id}]\n{req.message}'
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
                raise HTTPException(status_code=400, detail=f"work_dir mismatch: existing chat for topic '{req.topic}' has work_dir '{existing_chat.work_dir}', got '{work_dir}'. Use --new to create a new chat with the new work_dir.")
            if not work_dir:
                work_dir = existing_chat.work_dir
        updated_chat = await chat_service.append_message(chat_id, user_msg)
        # Set running immediately so frontend shows running state without waiting for worker
        updated_chat.running = True
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat_by_id(updated_chat)
    else:
        chat = await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)
        # Set running immediately so frontend shows running state without waiting for worker
        chat.running = True
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat(user_id, chat)

    # Enqueue worker
    send_chat_message(chat_id, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, role=role, topic=req.topic, backend=req.backend)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
