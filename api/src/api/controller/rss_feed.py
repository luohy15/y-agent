from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.service import rss_feed as rss_feed_service

router = APIRouter(prefix="/rss-feed")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateFeedRequest(BaseModel):
    url: str
    title: Optional[str] = None


class UpdateFeedRequest(BaseModel):
    rss_feed_id: str
    title: Optional[str] = None


class FeedIdRequest(BaseModel):
    rss_feed_id: str


@router.get("/list")
async def list_feeds(request: Request):
    user_id = _get_user_id(request)
    feeds = rss_feed_service.list_feeds(user_id)
    return [f.to_dict() for f in feeds]


@router.post("")
async def create_feed(req: CreateFeedRequest, request: Request):
    user_id = _get_user_id(request)
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    feed = rss_feed_service.add_feed(user_id, url, title=req.title)
    return feed.to_dict()


@router.post("/update")
async def update_feed(req: UpdateFeedRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"rss_feed_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    feed = rss_feed_service.update_feed(user_id, req.rss_feed_id, **fields)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed.to_dict()


@router.post("/delete")
async def delete_feed(req: FeedIdRequest, request: Request):
    user_id = _get_user_id(request)
    ok = rss_feed_service.delete_feed(user_id, req.rss_feed_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"ok": True}
