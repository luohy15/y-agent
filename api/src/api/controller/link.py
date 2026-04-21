import os
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import link as link_service


S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


router = APIRouter(prefix="/link")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateLinkRequest(BaseModel):
    url: str
    title: Optional[str] = None
    timestamp: Optional[int] = None


class BatchCreateLinksRequest(BaseModel):
    links: List[CreateLinkRequest]


class DownloadLinksRequest(BaseModel):
    urls: List[str]


class CreatePageLinkRequest(BaseModel):
    path: str
    title: Optional[str] = None
    content: Optional[str] = None


class ActivityIdRequest(BaseModel):
    activity_id: str


@router.get("/list")
async def list_links(
    request: Request,
    start: Optional[int] = Query(None),
    end: Optional[int] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    todo_id: Optional[str] = Query(None),
    downloaded: Optional[bool] = Query(None),
    source_feed_id: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    activity_ids = None
    if todo_id:
        from storage.repository.link_todo_relation import list_by_todo
        activity_ids = list_by_todo(user_id, todo_id)
        if not activity_ids:
            return []
    links = link_service.list_links(
        user_id, start=start, end=end, query=query,
        limit=limit, offset=offset, activity_ids=activity_ids,
        downloaded_only=bool(downloaded),
        source_feed_id=source_feed_id,
    )
    return [l.to_dict() for l in links]


@router.post("")
async def create_link(req: CreateLinkRequest, request: Request):
    user_id = _get_user_id(request)
    link = link_service.add_link(
        user_id, req.url, title=req.title, timestamp=req.timestamp,
    )
    return link.to_dict()


@router.post("/batch")
async def batch_create_links(req: BatchCreateLinksRequest, request: Request):
    user_id = _get_user_id(request)
    count = link_service.add_links_batch(
        user_id, [l.model_dump() for l in req.links],
    )
    return {"count": count}


@router.post("/download")
async def download_links(req: DownloadLinksRequest, request: Request):
    _get_user_id(request)
    results = link_service.request_downloads(req.urls)
    if any(item['download_status'] == 'pending' for item in results):
        link_service.trigger_batch_download()
    return results


@router.post("/from-page")
async def create_page_link(req: CreatePageLinkRequest, request: Request):
    user_id = _get_user_id(request)
    import time
    url = f"page://{req.path}"
    title = req.title or req.path.rsplit("/", 1)[-1].removesuffix(".md")
    timestamp = int(time.time() * 1000)
    link = link_service.add_link(user_id, url, title=title, timestamp=timestamp)
    if req.content:
        content_key = f"links/{link.link_id}/content.md"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=content_key,
            Body=req.content.encode("utf-8"),
            ContentType="text/markdown",
        )
        link_service.update_download_status(link.link_id, "done", content_key=content_key)
    else:
        link_service.update_download_status(link.link_id, "done", content_key=req.path)
    updated = link_service.get_link(user_id, link.activity_id)
    return updated.to_dict()


@router.get("/content")
async def get_link_content(
    request: Request,
    activity_id: Optional[str] = Query(None),
    link_id: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    if activity_id:
        link = link_service.get_link(user_id, activity_id)
    elif link_id:
        link = link_service.get_link_by_id(link_id)
    else:
        raise HTTPException(status_code=400, detail="activity_id or link_id required")
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    result = link.to_dict() if hasattr(link, 'to_dict') else {
        "link_id": link.link_id,
        "base_url": link.base_url,
        "title": link.title,
        "download_status": link.download_status,
        "content_key": link.content_key,
    }

    content_key = result.get("content_key")
    result["content"] = _read_s3_content(content_key) if content_key else None

    return result


def _read_s3_content(content_key: str) -> Optional[str]:
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=content_key)
        return obj["Body"].read().decode("utf-8")
    except ClientError:
        return None


@router.post("/delete")
async def delete_link(req: ActivityIdRequest, request: Request):
    user_id = _get_user_id(request)
    success = link_service.delete_link(user_id, req.activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link activity not found")
    return {"ok": True}
