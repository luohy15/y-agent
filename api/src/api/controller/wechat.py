import asyncio
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from api.util import wechat_media
from storage.database.base import get_db
from storage.service import wechat

router = APIRouter(prefix="/wechat")
Identifier = Annotated[str, Field(min_length=1, max_length=256)]
Token = Annotated[str, Field(min_length=1, max_length=8192)]


class Empty(BaseModel):
    model_config = {"extra": "forbid"}


class Session(BaseModel):
    model_config = {"extra": "forbid"}
    session_id: Identifier


class Poll(BaseModel):
    model_config = {"extra": "forbid"}
    session_id: Identifier
    pin: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class Send(BaseModel):
    model_config = {"extra": "forbid"}
    text: Annotated[str, Field(min_length=1, max_length=120000)]


class Revoke(BaseModel):
    model_config = {"extra": "forbid"}
    peer: Identifier


class PartialText(BaseModel):
    model_config = {"extra": "ignore"}
    start: Annotated[str, Field(max_length=64000)] | None = None
    end: Annotated[str, Field(max_length=64000)] | None = None
    startindex: Any = None
    endindex: Any = None
    quotemd5: Annotated[str, Field(max_length=64)] | None = None


class Quote(BaseModel):
    model_config = {"extra": "forbid"}
    svr_id: Identifier | None = None
    text: Annotated[str, Field(max_length=64000)] | None = None
    title: Annotated[str, Field(max_length=64000)] | None = None
    media_kind: Identifier | None = None
    media_name: Annotated[str, Field(max_length=1024)] | None = None
    partial_text: PartialText | None = None


class MediaItem(BaseModel):
    model_config = {"extra": "forbid"}
    kind: Literal["image", "file", "voice"]
    full_url: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    encrypt_query_param: Annotated[str, Field(max_length=4096)] | None = None
    aes_key: Annotated[str, Field(max_length=256)] | None = None
    aeskey: Annotated[str, Field(max_length=256)] | None = None
    file_name: Annotated[str, Field(max_length=1024)] | None = None
    size: Annotated[int, Field(ge=0)] | None = None
    duration_ms: Annotated[int, Field(ge=0)] | None = None
    encode_type: Annotated[int, Field(ge=0)] | None = None
    sample_rate: Annotated[int, Field(ge=0)] | None = None


class Inbound(BaseModel):
    model_config = {"extra": "forbid"}
    account: Identifier
    message_id: Identifier
    peer: Identifier
    text: Annotated[str, Field(max_length=64000)] = ""
    context_token: Token | None = None
    media: bool = False
    media_kind: Identifier | None = None
    media_name: Annotated[str, Field(max_length=1024)] | None = None
    media_items: Annotated[list[MediaItem], Field(max_length=9)] = Field(default_factory=list)
    quote: Quote | None = None


class Ack(BaseModel):
    model_config = {"extra": "forbid"}
    account: Identifier
    outbox_id: Identifier
    lease: Identifier
    ok: bool
    provider_message_id: Annotated[str, Field(max_length=256)] | None = None


class Claim(BaseModel):
    model_config = {"extra": "forbid"}
    account: Identifier


class Heartbeat(BaseModel):
    model_config = {"extra": "forbid"}
    account: Identifier
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


def parse_optional(data, model):
    if not data.strip():
        return model()
    return parse_body(data, model)


def invoke(call, *args):
    try:
        return call(*args)
    except wechat.ChannelError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except Exception:
        raise HTTPException(503, "Channel operation unavailable") from None


def _no_query(request):
    if request.query_params:
        raise HTTPException(422, "Binding accepts no query parameters")


@router.post("/bind/start")
async def start(request: Request):
    _no_query(request)
    parse_optional(await read_bytes(request), Empty)
    return await run_in_threadpool(invoke, wechat.start, request.state.user_id)


@router.post("/bind/poll")
async def poll(request: Request):
    _no_query(request)
    body = parse_body(await read_bytes(request), Poll)
    return await run_in_threadpool(invoke, wechat.poll, request.state.user_id, body.session_id, body.pin)


@router.post("/bind/cancel")
async def cancel(request: Request):
    _no_query(request)
    body = parse_body(await read_bytes(request), Session)
    return await run_in_threadpool(invoke, wechat.cancel, request.state.user_id, body.session_id)


@router.get("/status")
def status(request: Request):
    return invoke(wechat.status, request.state.user_id)


@router.get("/peers")
def peers(request: Request):
    return invoke(wechat.peers, request.state.user_id)


@router.post("/unbind")
def unbind(request: Request):
    return invoke(wechat.unbind, request.state.user_id)


@router.post("/revoke")
async def revoke(request: Request):
    body = parse_body(await read_bytes(request), Revoke)
    return await run_in_threadpool(invoke, wechat.revoke, request.state.user_id, body.peer)


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
        if action not in ("heartbeat", "inbound", "claim", "ack", "accounts"):
            raise HTTPException(404)
        wechat.authenticate(token)
        if action == "heartbeat":
            body = parse_body(data or b"{}", Heartbeat)
        elif action == "inbound":
            body = parse_body(data, Inbound)
        elif action == "claim":
            body = parse_body(data, Claim)
        elif action == "ack":
            body = parse_body(data, Ack)
        else:
            body = parse_optional(data, Empty)
        with get_db() as db:
            if action == "accounts":
                return wechat.active_accounts(db)
            account = wechat.account_by_id(
                db, body.account, for_update=action in ("heartbeat", "claim", "ack"))
            if action == "heartbeat":
                account.heartbeat = int(time.time())
                if body.polled:
                    account.last_poll = account.heartbeat
                return {"ok": True}
            if action == "inbound":
                result = asyncio.run(wechat.inbound(
                    db, account, media_handler=wechat_media.handle_media,
                    **body.model_dump(exclude={"account"})))
            elif action == "claim":
                return wechat.claim(db, account)
            else:
                return wechat.ack(db, account, outbox_id=body.outbox_id, lease=body.lease,
                                  ok=body.ok, provider_message_id=body.provider_message_id)
        if action == "inbound":
            asyncio.run(wechat.deliver_receipt(body.account, body.message_id))
        return result
    except wechat.ChannelError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Channel operation unavailable") from None
