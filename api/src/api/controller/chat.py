import asyncio
import json
import os
from typing import Optional

import boto3
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from storage.service import chat as chat_service
from storage.util import generate_id, generate_message_id, get_iso8601_timestamp, get_unix_timestamp
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


def _send_chat_message(chat_id: str):
    """Send a message to trigger the worker for a chat.

    Uses SQS when SQS_QUEUE_URL is set (production/Lambda).
    Falls back to Celery with filesystem broker for local dev.
    """
    queue_url = os.environ.get("SQS_QUEUE_URL")
    if queue_url:
        client = _get_sqs_client()
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"chat_id": chat_id}),
        )
        return

    app = _get_celery_app()
    app.send_task("worker.tasks.process_chat", args=[chat_id])


class CreateChatRequest(BaseModel):
    prompt: str
    bot_name: Optional[str] = None
    chat_id: Optional[str] = None


class CreateChatResponse(BaseModel):
    chat_id: str


class ApproveRequest(BaseModel):
    chat_id: str
    approved: bool


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def get_chats(request: Request, query: Optional[str] = Query(None)):
    user_id = _get_user_id(request)
    chats = await chat_service.list_chats(user_id=user_id, query=query)
    return [
        {
            "chat_id": c.chat_id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
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
        "timestamp": get_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp(),
        "id": generate_message_id(),
    })

    # Create in DB with status=pending
    await chat_service.create_chat(
        messages=[user_msg],
        chat_id=chat_id,
        status="pending",
        bot_name=req.bot_name,
        user_id=user_id,
    )

    _send_chat_message(chat_id)
    return CreateChatResponse(chat_id=chat_id)


@router.post("/approve")
async def post_approve(req: ApproveRequest):
    chat = await chat_service.get_chat_by_id(req.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if chat.status != "waiting_approval":
        raise HTTPException(status_code=400, detail="chat is not waiting for approval")
    status = "approved" if req.approved else "denied"
    await chat_service.update_chat_status(req.chat_id, status)
    _send_chat_message(req.chat_id)
    return {"ok": True}


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

            status = chat.status or ""
            if status in ("completed", "failed"):
                yield {"event": "done", "data": json.dumps({"status": status})}
                return

            if status == "waiting_approval":
                # Find the last assistant message - its tool/arguments fields
                # indicate what needs approval
                for m in reversed(messages):
                    if m.role == "assistant" and m.tool:
                        yield {
                            "event": "ask",
                            "data": json.dumps({
                                "tool_name": m.tool,
                                "tool_args": m.arguments or {},
                            }),
                        }
                        break

            await asyncio.sleep(1)

    return EventSourceResponse(event_stream())
