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
    trace_id: str
    from_skill: str
    force_new: Optional[bool] = False


class NotifyResponse(BaseModel):
    chat_id: str
    trace_id: str


@router.post("")
async def post_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

    # Build message content with trace metadata prefix
    msg_content = f'[trace:{req.trace_id} from:{req.from_skill} to:{req.skill}]\n{req.message}'
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

    # Resolve work_dir for existing chat
    work_dir = req.work_dir
    if chat_id:
        existing_chat = await chat_service.get_chat_by_id(chat_id)
        if existing_chat and existing_chat.work_dir:
            if work_dir and work_dir != existing_chat.work_dir:
                raise HTTPException(status_code=400, detail=f"work_dir mismatch: chat has '{existing_chat.work_dir}', got '{work_dir}'")
            if not work_dir:
                work_dir = existing_chat.work_dir
        await chat_service.append_message(chat_id, user_msg)
    else:
        # Priority 3: create new chat
        chat_id = generate_id()
        await chat_service.create_chat(user_id, messages=[user_msg], chat_id=chat_id)

    # Enqueue worker (bot_name = skill name, pass trace context via queue)
    send_chat_message(chat_id, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, skill=req.skill)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
