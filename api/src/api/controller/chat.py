import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from storage.service import bot_config as bot_service
from storage.service import chat as chat_service
from storage.service.chat import send_chat_message
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
from storage.entity.dto import Chat, Message
from storage.repository.chat import ChatIdCollision
from api.util.images import resolve_message_image_paths

router = APIRouter(prefix="/chat")


class ImageUpload(BaseModel):
    filename: str
    content_base64: str


class CreateChatRequest(BaseModel):
    prompt: str
    images: Optional[List[str]] = None
    image_uploads: Optional[List[ImageUpload]] = None
    bot_name: Optional[str] = None
    bot_tier: Optional[str] = None
    chat_id: Optional[str] = None
    vm_name: Optional[str] = None
    work_dir: Optional[str] = None
    post_hooks: Optional[list] = None
    reasoning_effort: Optional[str] = None


class CreateChatResponse(BaseModel):
    chat_id: str


class SendMessageRequest(BaseModel):
    chat_id: str
    prompt: str
    images: Optional[List[str]] = None
    image_uploads: Optional[List[ImageUpload]] = None
    bot_name: Optional[str] = None
    bot_tier: Optional[str] = None
    vm_name: Optional[str] = None
    work_dir: Optional[str] = None
    post_hooks: Optional[list] = None
    reasoning_effort: Optional[str] = None


class StopChatRequest(BaseModel):
    chat_id: str


class AttachImageRequest(BaseModel):
    chat_id: str
    images: Optional[List[str]] = None
    vm_name: Optional[str] = None


def _latest_assistant_message(chat):
    for msg in reversed(chat.messages):
        if msg.role == "assistant":
            return msg
    return None


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _append_delivered_images(msg, image_paths: List[str]) -> bool:
    existing = list(msg.telegram_delivered_images or [])
    seen = set(existing)
    changed = False
    for image_path in image_paths:
        if image_path in seen:
            continue
        existing.append(image_path)
        seen.add(image_path)
        changed = True
    if changed:
        msg.telegram_delivered_images = existing
    return changed


def _resolve_attach_vm_config(user_id: int, chat, vm_name: Optional[str]):
    from agent.config import resolve_vm_config
    return resolve_vm_config(user_id, vm_name, work_dir=getattr(chat, "work_dir", None))


def _deliver_attached_images_to_telegram(user_id: int, chat, target, image_paths: List[str], vm_name: Optional[str] = None) -> List[str]:
    if not image_paths or not chat.topic:
        return []

    from storage.service.telegram import resolve_target
    from agent.telegram_delivery import send_telegram_photo_reference

    telegram_target = resolve_target(user_id, topic=chat.topic)
    if not telegram_target:
        return []

    bot_token, tg_chat_id, topic_id = telegram_target
    try:
        vm_config = _resolve_attach_vm_config(user_id, chat, vm_name)
    except Exception as exc:
        logger.warning("attach-image telegram delivery: vm_config resolution failed chat_id={}: {}", chat.id, exc)
        vm_config = None

    caption = target.content.strip() if isinstance(target.content, str) and target.content.strip() else None
    delivered = []
    for index, image_path in enumerate(image_paths):
        try:
            sent = send_telegram_photo_reference(
                bot_token,
                tg_chat_id,
                image_path,
                caption=caption if index == 0 and caption else None,
                topic_id=topic_id,
                vm_config=vm_config,
            )
        except Exception as exc:
            logger.exception("attach-image telegram delivery failed chat_id={} image={}: {}", chat.id, image_path, exc)
            continue
        if sent:
            delivered.append(image_path)

    return delivered


REASONING_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def _normalize_reasoning_effort(reasoning_effort: Optional[str]) -> Optional[str]:
    if reasoning_effort is None:
        return None
    normalized = reasoning_effort.lower()
    if normalized not in REASONING_EFFORT_LEVELS:
        raise HTTPException(
            status_code=400,
            detail="reasoning_effort must be one of: low, medium, high, xhigh, max",
        )
    return normalized


def _message_dict(role: str, content: str, images: Optional[List[str]] = None, reasoning_effort: Optional[str] = None) -> dict:
    data = {
        "role": role,
        "content": content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    }
    if images:
        data["images"] = images
    if reasoning_effort is not None:
        data["reasoning_effort"] = _normalize_reasoning_effort(reasoning_effort)
    return data


@router.get("/bot-options")
async def get_bot_options(request: Request):
    return [
        {
            "name": config.name,
            "backend": config.backend or config.api_type,
            "model": config.model,
        }
        for config in bot_service.list_configs(_get_user_id(request))
    ]


@router.post("")
async def post_create_chat(req: CreateChatRequest, request: Request):
    user_id = _get_user_id(request)
    # Caller-supplied ids: single attempt, ChatIdCollision → 409.
    # Generated ids: create_chat retries allocate+insert on race (no pre-mint).
    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, req.vm_name, work_dir=req.work_dir)
    images = resolve_message_image_paths(req.images, req.image_uploads, prefix="chat-upload", vm_config=vm_config)

    # Build user message
    user_msg = Message.from_dict(_message_dict("user", req.prompt, images, req.reasoning_effort))

    try:
        chat = await chat_service.create_chat(
            user_id,
            messages=[user_msg],
            chat_id=req.chat_id,
        )
    except ChatIdCollision as exc:
        raise HTTPException(status_code=409, detail=f"chat_id '{exc.chat_id}' already exists") from exc

    # Set running immediately so frontend shows running state without waiting for worker
    chat.running = True
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat(user_id, chat)

    send_chat_message(chat.id, bot_name=req.bot_name, bot_tier=req.bot_tier, user_id=user_id, vm_name=req.vm_name, work_dir=req.work_dir, post_hooks=req.post_hooks)
    return CreateChatResponse(chat_id=chat.id)


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

    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, req.vm_name, work_dir=work_dir)
    images = resolve_message_image_paths(req.images, req.image_uploads, prefix="chat-upload", vm_config=vm_config)
    prompt = chat_service.maybe_append_handoff_reminder(chat, req.prompt)
    user_msg = Message.from_dict(_message_dict("user", prompt, images, req.reasoning_effort))
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
        send_chat_message(req.chat_id, bot_name=req.bot_name, bot_tier=req.bot_tier, user_id=user_id, vm_name=req.vm_name, work_dir=work_dir, post_hooks=req.post_hooks)

    return {"ok": True}


@router.post("/attach-image")
async def post_attach_image(req: AttachImageRequest, request: Request):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, req.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    images = resolve_message_image_paths(req.images, None, prefix="attach")
    if not images:
        raise HTTPException(status_code=400, detail="at least one image is required")

    target = _latest_assistant_message(chat)
    if target is None:
        raise HTTPException(status_code=409, detail="no assistant message yet to attach to")

    existing = list(target.images or [])
    seen = set(existing)
    added = []
    for image_path in images:
        if image_path in seen:
            continue
        existing.append(image_path)
        added.append(image_path)
        seen.add(image_path)
    target.images = existing

    delivered = []
    if not chat.running:
        delivered = _deliver_attached_images_to_telegram(user_id, chat, target, added, vm_name=req.vm_name)
        _append_delivered_images(target, delivered)

    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)
    return {"ok": True, "chat_id": req.chat_id, "count": len(added), "images": existing, "telegram_delivered_images": delivered}


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


class TraceReadBulkRequest(BaseModel):
    trace_ids: List[str]


@router.post("/trace/read")
async def post_mark_trace_read(req: TraceReadRequest, request: Request):
    user_id = _get_user_id(request)
    count = chat_service.mark_trace_read(user_id, req.trace_id)
    return {"ok": True, "count": count}


@router.post("/trace/read_bulk")
async def post_mark_trace_read_bulk(req: TraceReadBulkRequest, request: Request):
    user_id = _get_user_id(request)
    count = 0
    for trace_id in req.trace_ids:
        count += chat_service.mark_trace_read(user_id, trace_id)
    return {"ok": True, "count": count}


@router.post("/trace/unread")
async def post_mark_trace_unread(req: TraceReadRequest, request: Request):
    user_id = _get_user_id(request)
    chat_id = chat_service.mark_trace_unread(user_id, req.trace_id)
    return {"ok": True, "chat_id": chat_id}


class TraceReadAllRequest(BaseModel):
    status: Optional[str] = None
    query: Optional[str] = None
    unread: Optional[bool] = None


@router.post("/trace/read_all")
async def post_mark_trace_read_all(req: TraceReadAllRequest, request: Request):
    user_id = _get_user_id(request)
    status = None if req.status in (None, "", "all") else req.status
    count = chat_service.mark_all_traces_read(user_id, status=status, query=req.query, unread=req.unread)
    return {"ok": True, "count": count}


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
    if chat.skill:
        result["skill"] = chat.skill
    if chat.trace_id:
        result["trace_id"] = chat.trace_id
    if chat.backend:
        result["backend"] = chat.backend
    if chat.bot_name:
        result["bot_name"] = chat.bot_name
    if chat.tier:
        result["tier"] = chat.tier
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
    images: Optional[List[str]] = None
    image_uploads: Optional[List[ImageUpload]] = None
    topic: Optional[str] = None
    skill: Optional[str] = None
    chat_id: Optional[str] = None
    work_dir: Optional[str] = None
    trace_id: Optional[str] = None
    from_topic: Optional[str] = None
    force_new: Optional[bool] = False
    from_chat_id: Optional[str] = None
    bot_name: Optional[str] = None
    bot_tier: Optional[str] = None
    reasoning_effort: Optional[str] = None


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

    # Resolve target chat: explicit chat_id > topic+trace lookup > new.
    # Do not pre-mint a generated id: create_chat retries allocate+insert, and
    # the final id must land in the to_chat: prefix (built after create).
    existing_chat = None
    chat_id = None
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

    # Build message content with trace metadata prefix (only include parts we have).
    # For a brand-new chat the to_chat: id is filled in after create (see below).
    def _notify_content(to_chat_id: str) -> str:
        parts = []
        if req.trace_id:
            parts.append(f'trace:{req.trace_id}')
        if req.from_topic:
            parts.append(f'from:{req.from_topic}')
        if req.topic:
            parts.append(f'to:{req.topic}')
        if req.from_chat_id:
            parts.append(f'from_chat:{req.from_chat_id}')
        parts.append(f'to_chat:{to_chat_id}')
        return f"[{' '.join(parts)}]\n{req.message}"

    vm_work_dir = req.work_dir or (existing_chat.work_dir if existing_chat else None)
    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, work_dir=vm_work_dir)
    images = resolve_message_image_paths(req.images, req.image_uploads, prefix="chat-notify-upload", vm_config=vm_config)

    # Resolve work_dir and append/create chat
    work_dir = req.work_dir
    from storage.repository import chat as chat_repo
    if existing_chat:
        msg_content = chat_service.maybe_append_handoff_reminder(
            existing_chat, _notify_content(chat_id),
        )
        user_msg = Message.from_dict(_message_dict("user", msg_content, images, req.reasoning_effort))
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
        # create_chat mints + inserts with race retry; rebuild the message so
        # to_chat: matches the final id.
        def build(new_id: str):
            user_msg = Message.from_dict(
                _message_dict("user", _notify_content(new_id), images, req.reasoning_effort)
            )
            chat = Chat(
                id=new_id,
                create_time=get_utc_iso8601_timestamp(),
                update_time=get_utc_iso8601_timestamp(),
                messages=[user_msg],
                topic=req.topic,
                skill=skill,
                running=True,
            )
            return chat

        # Use insert_generated_chat so topic/skill/running land on the first write
        # and the allocate+insert race is retried (plan 3131 D3).
        chat = await chat_service.insert_generated_chat(user_id, build)
        chat_id = chat.id
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
        send_chat_message(chat_id, bot_name=req.bot_name, bot_tier=req.bot_tier, user_id=user_id, work_dir=work_dir, trace_id=req.trace_id, topic=req.topic, skill=skill)

    return NotifyResponse(chat_id=chat_id, trace_id=req.trace_id)
