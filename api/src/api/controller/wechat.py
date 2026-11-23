import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from storage.database.base import get_db
from storage.service import wechat

router = APIRouter(prefix="/wechat")
Identifier = Annotated[str, Field(min_length=1, max_length=256)]
Token = Annotated[str, Field(min_length=1, max_length=8192)]


class Binding(BaseModel):
    model_config = {"extra": "forbid"}
    account: Identifier
    peer: Identifier
    bot_token: Token


class Send(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=120000)]


class Inbound(BaseModel):
    message_id: Identifier
    peer: Identifier
    text: Annotated[str, Field(max_length=64000)] = ""
    context_token: Token | None = None
    media: bool = False


class Ack(BaseModel):
    outbox_id: Identifier
    lease: Identifier
    ok: bool


class Heartbeat(BaseModel):
    polled: bool = False


async def read_bytes(request):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 600000:
            raise HTTPException(413, "Message too large")
        data.extend(chunk)
    return bytes(data)


def parse_body(data, model):
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "Invalid channel request") from None


def invoke(call, *args):
    try:
        return call(*args)
    except wechat.ChannelError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except Exception:
        raise HTTPException(503, "Channel operation unavailable") from None


@router.post("/bind/complete")
async def complete(request: Request):
    if request.query_params:
        raise HTTPException(422, "Binding accepts no query parameters")
    body = parse_body(await read_bytes(request), Binding)
    return await run_in_threadpool(invoke, wechat.bind, request.state.user_id, body.account, body.peer, body.bot_token)


@router.get("/status")
def status(request: Request):
    return invoke(wechat.owner_state, request.state.user_id, "status")


@router.post("/unbind")
def unbind(request: Request):
    return invoke(wechat.owner_state, request.state.user_id, "unbind")


@router.post("/send")
async def send(request: Request):
    body = parse_body(await read_bytes(request), Send)
    return await run_in_threadpool(invoke, wechat.send, request.state.user_id, body.text)


@router.post("/bridge/{action}")
async def bridge(action: str, request: Request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not header[7:]:
        raise HTTPException(401, "Missing bridge token")
    return await run_in_threadpool(bridge_action, action, header[7:], await read_bytes(request))


def bridge_action(action, token, data):
    try:
        with get_db() as db:
            account = wechat.authenticate(db, token)
            if action == "heartbeat":
                account.heartbeat = int(time.time())
                if parse_body(data or b"{}", Heartbeat).polled:
                    account.last_poll = account.heartbeat
                return {"ok": True}
            if action == "inbound":
                body = parse_body(data, Inbound)
                result = asyncio.run(wechat.inbound(db, account, **body.model_dump()))
            elif action == "claim":
                return wechat.claim(db, account)
            elif action == "ack":
                body = parse_body(data, Ack)
                return wechat.ack(db, account, **body.model_dump())
            else:
                raise HTTPException(404)
        if action == "inbound":
            asyncio.run(wechat.deliver_receipt(token, body.message_id))
        return result
    except wechat.ChannelError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Channel operation unavailable") from None
