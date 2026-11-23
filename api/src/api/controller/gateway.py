from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from storage.service import channel as channel_service, gateway

router = APIRouter(prefix="/gateway")


class SendBody(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=120000)
    reply_chat: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{6}$")


class ConfigBody(BaseModel):
    model_config = {"extra": "forbid"}
    channel: Literal["wechat", "telegram", "default"]


def _user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/channels")
async def channels(request: Request):
    return await run_in_threadpool(channel_service.list_channels, _user_id(request))


@router.post("/channels/{channel}/unbind")
async def unbind_channel(channel: Literal["telegram", "wechat"], request: Request):
    try:
        return await run_in_threadpool(channel_service.unbind, _user_id(request), channel)
    except channel_service.ChannelError as exc:
        raise HTTPException(exc.status, exc.detail) from None


@router.post("/send")
async def send(body: SendBody, request: Request):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text is required")
    result = await run_in_threadpool(gateway.send, _user_id(request), text, body.reply_chat)
    if result.error == "chat_not_found":
        raise HTTPException(404, "chat not found")
    if not result:
        raise HTTPException(503, result.to_dict())
    return result.to_dict()


@router.get("/status")
async def status(request: Request):
    return await run_in_threadpool(gateway.status, _user_id(request))


@router.put("/config")
async def config(body: ConfigBody, request: Request):
    try:
        preference = await run_in_threadpool(gateway.set_channel, _user_id(request), body.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"preference": preference, "channel": body.channel}
