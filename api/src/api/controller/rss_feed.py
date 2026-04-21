from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.service import rss_feed as rss_feed_service

router = APIRouter(prefix="/rss-feed")

_ALLOWED_FEED_TYPES = {'rss', 'scrape'}


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _validate_feed_type(feed_type: Optional[str]) -> Optional[str]:
    if feed_type is None:
        return None
    if feed_type not in _ALLOWED_FEED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"feed_type must be one of {sorted(_ALLOWED_FEED_TYPES)}",
        )
    return feed_type


def _validate_scrape_config(
    feed_type: Optional[str],
    scrape_config: Optional[Dict[str, Any]],
) -> None:
    if feed_type != 'scrape':
        return
    if not scrape_config or not isinstance(scrape_config, dict):
        raise HTTPException(
            status_code=400,
            detail="scrape_config is required when feed_type='scrape'",
        )
    item_selector = scrape_config.get('item_selector')
    if not isinstance(item_selector, str) or not item_selector.strip():
        raise HTTPException(
            status_code=400,
            detail="scrape_config.item_selector is required and must be a non-empty string",
        )


class CreateFeedRequest(BaseModel):
    url: str
    title: Optional[str] = None
    feed_type: Optional[str] = None
    scrape_config: Optional[Dict[str, Any]] = None


class UpdateFeedRequest(BaseModel):
    rss_feed_id: str
    title: Optional[str] = None
    feed_type: Optional[str] = None
    scrape_config: Optional[Dict[str, Any]] = None


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
    feed_type = _validate_feed_type(req.feed_type) or 'rss'
    _validate_scrape_config(feed_type, req.scrape_config)
    feed = rss_feed_service.add_feed(
        user_id,
        url,
        title=req.title,
        feed_type=feed_type,
        scrape_config=req.scrape_config,
    )
    return feed.to_dict()


@router.post("/update")
async def update_feed(req: UpdateFeedRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"rss_feed_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    feed_type = _validate_feed_type(req.feed_type)
    if feed_type is not None or req.scrape_config is not None:
        existing = rss_feed_service.get_feed(user_id, req.rss_feed_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Feed not found")
        effective_type = feed_type or existing.feed_type or 'rss'
        effective_config = req.scrape_config if req.scrape_config is not None else existing.scrape_config
        _validate_scrape_config(effective_type, effective_config)
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
