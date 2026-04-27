import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from storage.service import chat as chat_service
from storage.service.chat import send_chat_message
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from storage.entity.dto import Message

router = APIRouter(prefix="/chat")


class CreateChatRequest(BaseModel):
    prompt: str
    bot_name: Optional[str] = None
    chat_id: Optional[str] = None
    vm_name: Optional[str] = None
    work_dir: Optional[str] = None
    post_hooks: Optional[list] = None


class CreateChatResponse(BaseModel):
    chat_id: str


class SendMessageRequest(BaseModel):
    chat_id: str
    prompt: str
    bot_name: Optional[str] = None
    vm_name: Optional[str] = None
    work_dir: Optional[str] = None
    post_hooks: Optional[list] = None


class StopChatRequest(BaseModel):
    chat_id: str


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def get_chats(request: Request, query: Optional[str] = Query(None), trace_id: Optional[str] = Query(None), topic: Optional[str] = Query(None), status: Optional[str] = Query(None), unread: Optional[bool] = Query(None), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    user_id = _get_user_id(request)
    chats = await chat_service.list_chats(user_id, query=query, limit=limit, offset=offset, trace_id=trace_id, topic=topic, status=status, unread=unread)
    return [
        {
            "chat_id": c.chat_id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "topic": c.topic,
            "trace_id": c.trace_id,
            "backend": c.backend,
            "status": c.status,
            "unread": c.unread,
        }
        for c in chats
    ]


@router.post("")
async def post_create_chat(req: CreateChatRequest, request: Request):
    chat_id = req.chat_id or generate_id()
    user_id = _get_user_id(request)

    # Build user message
    user_msg = Message.from_dict({
        "role": "user",
        "content": req.prompt,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })

    chat = await chat_service.create_chat(
        user_id,
        messages=[user_msg],
        chat_id=chat_id,
    )

    # Set running immediately so frontend shows running state without waiting for worker
    chat.running = True
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat(user_id, chat)

    send_chat_message(chat_id, bot_name=req.bot_name, user_id=user_id, vm_name=req.vm_name, work_dir=req.work_dir, post_hooks=req.post_hooks)
    return CreateChatResponse(chat_id=chat_id)


@router.post("/message")
async def post_send_message(req: SendMessageRequest, request: Request):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, req.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    # Resolve work_dir: use existing chat.work_dir if not provided, validate if provided
    work_dir = req.work_dir
    if chat.work_dir:
        if work_dir and work_dir != chat.work_dir:
            raise HTTPException(status_code=400, detail=f"work_dir mismatch: chat has '{chat.work_dir}', got '{work_dir}'")
        if not work_dir:
            work_dir = chat.work_dir

    user_msg = Message.from_dict({
        "role": "user",
        "content": req.prompt,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })
    chat.messages.append(user_msg)
    chat.interrupted = False

    # If chat is running, don't queue a new task — the running worker will pick up
    # the new message via steer polling
    already_running = chat.running
    if not already_running:
        # Set running immediately so frontend shows running state without waiting for worker
        chat.running = True

    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)

    if not already_running:
        send_chat_message(req.chat_id, bot_name=req.bot_name, user_id=user_id, vm_name=req.vm_name, work_dir=work_dir, post_hooks=req.post_hooks)

    return {"ok": True}


@router.post("/stop")
async def post_stop_chat(req: StopChatRequest):
    chat = await chat_service.get_chat_by_id(req.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    chat.interrupted = True

    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)
    return {"ok": True}


class MarkReadRequest(BaseModel):
    chat_id: str


@router.post("/read")
async def post_mark_read(req: MarkReadRequest):
    chat_service.mark_chat_read(req.chat_id)
    return {"ok": True}


class TraceReadRequest(BaseModel):
    trace_id: str


@router.post("/trace/read")
async def post_mark_trace_read(req: TraceReadRequest, request: Request):
    user_id = _get_user_id(request)
    count = chat_service.mark_trace_read(user_id, req.trace_id)
    return {"ok": True, "count": count}


@router.post("/trace/unread")
async def post_mark_trace_unread(req: TraceReadRequest, request: Request):
    user_id = _get_user_id(request)
    chat_id = chat_service.mark_trace_unread(user_id, req.trace_id)
    return {"ok": True, "chat_id": chat_id}


class ShareChatRequest(BaseModel):
    chat_id: str
    message_id: Optional[str] = None
    password: Optional[str] = None
    generate_password: bool = False


@router.post("/share")
async def post_share_chat(req: ShareChatRequest, request: Request):
    from storage import share_password as sp
    user_id = _get_user_id(request)

    generated_password: Optional[str] = None
    password_hash: Optional[str] = None
    if req.generate_password and not (req.password and req.password.strip()):
        generated_password = sp.generate_password()
        password_hash = sp.hash_password(generated_password)
    elif req.password and req.password.strip():
        password_hash = sp.hash_password(req.password)

    share_id = await chat_service.create_share(user_id, req.chat_id, req.message_id, password_hash=password_hash)
    resp = {"share_id": share_id}
    if generated_password is not None:
        resp["password"] = generated_password
    return resp


@router.get("/share")
async def get_share_chat(share_id: str = Query(...), password: Optional[str] = Query(None)):
    from storage.service.user import get_default_user_id
    from storage.repository import chat as chat_repo
    from storage import share_password as sp

    default_user_id = get_default_user_id()
    chat = await chat_service.get_chat(default_user_id, share_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="shared chat not found")

    password_hash = chat_repo.get_share_password_hash(default_user_id, share_id)
    if password_hash:
        if not password:
            raise HTTPException(status_code=401, detail={"password_required": True})
        allowed, retry_after = sp.check_rate_limit(share_id)
        if not allowed:
            raise HTTPException(status_code=429, detail={"retry_after": retry_after})
        if not sp.verify_password(password, password_hash):
            sp.record_failure(share_id)
            raise HTTPException(status_code=403, detail="Invalid password")

    return {
        "chat_id": chat.id,
        "messages": [m.to_dict() for m in chat.messages],
        "create_time": chat.create_time,
        "origin_chat_id": chat.origin_chat_id,
        "origin_message_id": chat.origin_message_id,
    }


@router.get("/content")
async def get_chat_content(chat_id: str = Query(...), request: Request = None):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return {
        "chat_id": chat.id,
        "messages": [m.to_dict() for m in chat.messages],
        "create_time": chat.create_time,
        "update_time": chat.update_time,
    }


@router.get("/detail")
async def get_chat_detail(chat_id: str = Query(...), request: Request = None):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    result = {
        "chat_id": chat.id,
    }
    if chat.work_dir:
        result["work_dir"] = chat.work_dir
    if chat.topic:
        result["topic"] = chat.topic
    if chat.trace_id:
        result["trace_id"] = chat.trace_id
    if chat.backend:
        result["backend"] = chat.backend
    if chat.context_window is not None:
        result["input_tokens"] = chat.input_tokens
        result["output_tokens"] = chat.output_tokens
        result["cache_read_input_tokens"] = chat.cache_read_input_tokens
        result["cache_creation_input_tokens"] = chat.cache_creation_input_tokens
        result["context_window"] = chat.context_window
    return result


@router.get("/messages/snapshot")
async def get_chat_messages_snapshot(chat_id: str = Query(...), request: Request = None):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    # Auto mark as read when messages are fetched
    chat_service.mark_chat_read(chat_id)

    messages = []
    for idx, msg in enumerate(chat.messages):
        messages.append({"index": idx, "type": "message", "data": msg.to_dict()})

    return {
        "messages": messages,
        "running": chat.running,
        "interrupted": chat.interrupted,
    }


@router.get("/messages")
async def get_chat_messages(chat_id: str = Query(...), last_index: int = Query(0, ge=0)):
    async def event_stream():
        # Auto mark as read when messages are fetched
        chat_service.mark_chat_read(chat_id)

        idx = last_index
        while True:
            chat = await chat_service.get_chat_by_id(chat_id)
            if chat is None:
                yield {"event": "error", "data": json.dumps({"error": "chat not found"})}
                return

            messages = chat.messages
            while idx < len(messages):
                msg = messages[idx]
                msg_data = msg.to_dict()
                idx_val = idx
                idx += 1
                yield {
                    "event": "message",
                    "data": json.dumps({"index": idx_val, "type": "message", "data": msg_data}),
                }

            # Check if chat was interrupted
            if chat.interrupted:
                yield {"event": "done", "data": json.dumps({"status": "interrupted"})}
                return

            # Check if chat is done (last message is assistant with no tool_calls and not running)
            last_msg = messages[-1] if messages else None
            if last_msg and last_msg.role == "assistant" and not last_msg.tool_calls and not chat.running:
                yield {"event": "done", "data": json.dumps({"status": "completed"})}
                return

            await asyncio.sleep(1)

    return EventSourceResponse(event_stream())


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
    """Skill defaults to topic for non-root topics; --skill overrides."""
    if req.skill:
        return req.skill
    if req.topic and req.topic != "manager":
        return req.topic
    return None


@router.post("/notify")
async def post_chat_notify(req: NotifyRequest, request: Request):
    user_id = _get_user_id(request)

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

    # Root topics are long-lived conversations, not function calls — they have no
    # parent to "return" to, so notify callbacks targeting them are rejected.
    # The check fires on the resolved target chat's topic so that addressing a
    # root chat by `--chat-id` (the canonical post-1876 callback shape) is also
    # caught — pre-resolution `req.topic` is None in that case.
    # Two arms: existing chat → callback (reject; --new doesn't apply because
    # --chat-id semantically means "use this specific chat"); new chat → only
    # reject when --new isn't set (preserves `--topic manager --new` to start a
    # fresh root session).
    # Today there is exactly one root topic ("manager"); the check is hard-coded
    # to that name until the root-topic set becomes a first-class concept.
    if existing_chat and existing_chat.topic == "manager":
        raise HTTPException(
            status_code=400,
            detail="Root topic 'manager' does not accept notify callbacks. Send to from_chat instead, or use --new with --topic manager to start a fresh manager session.",
        )
    if not existing_chat and req.topic == "manager" and not req.force_new:
        raise HTTPException(
            status_code=400,
            detail="Root topic 'manager' does not accept notify callbacks. Use --new to start a fresh manager session, or send to a specific topic instead.",
        )

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
        # Stamp identity fields on creation.
        if req.topic:
            chat.topic = req.topic
        if skill:
            chat.skill = skill
        # Set running immediately so frontend shows running state without waiting for worker
        chat.running = True
        await chat_repo.save_chat(user_id, chat)
        already_running = False

        # Singleton root topic: a new chat claiming a topic without a trace_id is a
        # root chat (e.g. fresh manager session). Release the topic from any other
        # chat that still holds it so (user_id, topic) has a single owner.
        if req.topic and not req.trace_id:
            released = chat_repo.release_topic(user_id, req.topic, except_chat_id=chat_id)
            if released:
                logger.info("Released topic '{}' from {} previous chat(s) on new claim by {}", req.topic, released, chat_id)

    # Enqueue worker only if not already running
    if not already_running:
        send_chat_message(chat_id, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, topic=req.topic, skill=skill, backend=req.backend)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
