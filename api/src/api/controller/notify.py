from typing import Optional

from fastapi import APIRouter, HTTPException, Request
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
    message: str
    topic: Optional[str] = None
    skill: Optional[str] = None
    chat_id: Optional[str] = None
    work_dir: Optional[str] = None
    trace_id: Optional[str] = None
    from_topic: Optional[str] = None
    force_new: Optional[bool] = False
    from_chat_id: Optional[str] = None
    backend: Optional[str] = None


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: Optional[str] = None


def _resolve_skill(req: NotifyRequest) -> Optional[str]:
    """Skill defaults to topic for non-manager topics; --skill overrides."""
    if req.skill:
        return req.skill
    if req.topic and req.topic != "manager":
        return req.topic
    return None


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Root-topic chats (currently only "manager") are conversations, not function
    # calls — the API rejects callbacks targeting them. Anonymous chats (no topic)
    # and non-root topics are unaffected. --new is always allowed to start fresh.
    if req.topic == "manager" and not req.force_new:
        raise HTTPException(status_code=400, detail="Root topic 'manager' does not accept notify callbacks. Use --new to start a fresh manager session, or send to a specific topic instead.")

    # Derive role for backward-compat with the queue/chat schema (dropped in batch C).
    role = "manager" if req.topic == "manager" else ("worker" if req.topic else None)
    skill = _resolve_skill(req)

    # Resolve target chat: explicit chat_id > topic+trace lookup > new
    existing_chat = None
    if req.chat_id:
        existing_chat = await chat_service.get_chat_by_id(req.chat_id)
        if not existing_chat:
            raise HTTPException(status_code=404, detail=f"chat_id '{req.chat_id}' not found")
        if req.topic and existing_chat.topic and existing_chat.topic != req.topic:
            raise HTTPException(
                status_code=400,
                detail=f"topic mismatch: chat '{req.chat_id}' belongs to topic '{existing_chat.topic}', got '{req.topic}'. Use --new to create a new chat, or omit --chat-id to let the system find the right one."
            )
        chat_id = req.chat_id
    elif req.topic and req.trace_id and not req.force_new:
        from storage.repository.chat import find_chat_by_topic_and_trace
        found = find_chat_by_topic_and_trace(user_id, req.topic, req.trace_id)
        if found:
            chat_id = found.id
            existing_chat = await chat_service.get_chat_by_id(chat_id)
        else:
            chat_id = generate_id()
    else:
        chat_id = generate_id()

    # Build message content with trace metadata prefix (only include parts we have)
    parts = []
    if req.trace_id:
        parts.append(f'trace:{req.trace_id}')
    if req.from_topic:
        parts.append(f'from:{req.from_topic}')
    if req.topic:
        parts.append(f'to:{req.topic}')
    if req.from_chat_id:
        parts.append(f'from_chat:{req.from_chat_id}')
    parts.append(f'to_chat:{chat_id}')
    msg_content = f"[{' '.join(parts)}]\n{req.message}"
    user_msg = Message.from_dict({
        "role": "user",
        "content": msg_content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })

    # Resolve work_dir and append/create chat
    work_dir = req.work_dir
    from storage.repository import chat as chat_repo
    if existing_chat:
        if existing_chat.work_dir:
            if work_dir and work_dir != existing_chat.work_dir:
                raise HTTPException(status_code=400, detail=f"work_dir mismatch: existing chat '{chat_id}' has work_dir '{existing_chat.work_dir}', got '{work_dir}'. Use --new to create a new chat with the new work_dir.")
            if not work_dir:
                work_dir = existing_chat.work_dir
        updated_chat = await chat_service.append_message(chat_id, user_msg)
        updated_chat.interrupted = False
        # If chat is running, don't queue a new task — the running worker will pick up
        # the new message via steer polling
        already_running = updated_chat.running
        if not already_running:
            # Set running immediately so frontend shows running state without waiting for worker
            updated_chat.running = True
        await chat_repo.save_chat_by_id(updated_chat)
    else:
        chat = await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)
        # Stamp identity fields on creation. role/topic remain dropped in batch C; skill is the new home.
        if role:
            chat.role = role
        if req.topic:
            chat.topic = req.topic
        if skill:
            chat.skill = skill
        # Set running immediately so frontend shows running state without waiting for worker
        chat.running = True
        await chat_repo.save_chat(user_id, chat)
        already_running = False

    # Enqueue worker only if not already running
    if not already_running:
        send_chat_message(chat_id, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, role=role, topic=req.topic, skill=skill, backend=req.backend)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
