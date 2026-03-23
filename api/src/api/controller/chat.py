import asyncio
import json
import os
from typing import Optional

import boto3
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from storage.service import chat as chat_service
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp, backfill_tool_results
from storage.entity.dto import Message

router = APIRouter(prefix="/chat")


def _get_sqs_client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    endpoint_url = os.environ.get("SQS_ENDPOINT_URL")
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("sqs", **kwargs)


def _get_celery_app():
    """Create a minimal Celery app for dispatching tasks via filesystem broker."""
    from celery import Celery
    from storage.celery_config import BROKER_URL, BROKER_TRANSPORT_OPTIONS, RESULT_BACKEND

    app = Celery("api")
    app.conf.update(
        broker_url=BROKER_URL,
        broker_transport_options=BROKER_TRANSPORT_OPTIONS,
        result_backend=RESULT_BACKEND,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
    )
    return app


def _send_chat_message(chat_id: str, bot_name: str = None, user_id: int = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, skill: str = None):
    """Send a message to trigger the worker for a chat.

    Uses SQS when SQS_QUEUE_URL is set (production/Lambda).
    Falls back to Celery with filesystem broker for local dev.
    """
    payload = {"chat_id": chat_id}
    if bot_name:
        payload["bot_name"] = bot_name
    if user_id is not None:
        payload["user_id"] = user_id
    if vm_name:
        payload["vm_name"] = vm_name
    if work_dir:
        payload["work_dir"] = work_dir
    if post_hooks:
        payload["post_hooks"] = post_hooks
    if trace_id:
        payload["trace_id"] = trace_id
    if skill:
        payload["skill"] = skill

    queue_url = os.environ.get("SQS_QUEUE_URL")
    if queue_url:
        client = _get_sqs_client()
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload),
        )
        return

    app = _get_celery_app()
    app.send_task("worker.tasks.process_chat", args=[chat_id], kwargs={"bot_name": bot_name, "user_id": user_id, "vm_name": vm_name, "work_dir": work_dir, "post_hooks": post_hooks, "trace_id": trace_id, "skill": skill})


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
async def get_chats(request: Request, query: Optional[str] = Query(None), trace_id: Optional[str] = Query(None), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    user_id = _get_user_id(request)
    chats = await chat_service.list_chats(user_id, query=query, limit=limit, offset=offset, trace_id=trace_id)
    return [
        {
            "chat_id": c.chat_id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "skill": c.skill,
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

    _send_chat_message(chat_id, bot_name=req.bot_name, user_id=user_id, vm_name=req.vm_name, work_dir=req.work_dir, post_hooks=req.post_hooks)
    return CreateChatResponse(chat_id=chat_id)


@router.post("/message")
async def post_send_message(req: SendMessageRequest, request: Request):
    user_id = _get_user_id(request)
    chat = await chat_service.get_chat(user_id, req.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    # Backfill tool results so they are persisted
    backfill_tool_results(chat.messages, mode="cancelled")
    user_msg = Message.from_dict({
        "role": "user",
        "content": req.prompt,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })
    chat.messages.append(user_msg)
    chat.interrupted = False

    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)

    _send_chat_message(req.chat_id, bot_name=req.bot_name, user_id=user_id, vm_name=req.vm_name, work_dir=req.work_dir, post_hooks=req.post_hooks)
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


class ShareChatRequest(BaseModel):
    chat_id: str
    message_id: Optional[str] = None


@router.post("/share")
async def post_share_chat(req: ShareChatRequest, request: Request):
    user_id = _get_user_id(request)
    share_id = await chat_service.create_share(user_id, req.chat_id, req.message_id)
    return {"share_id": share_id}


@router.get("/share")
async def get_share_chat(share_id: str = Query(...)):
    from storage.service.user import get_default_user_id
    default_user_id = get_default_user_id()
    chat = await chat_service.get_chat(default_user_id, share_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="shared chat not found")
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
    return result


@router.get("/messages")
async def get_chat_messages(chat_id: str = Query(...), last_index: int = Query(0, ge=0)):
    async def event_stream():
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
