from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import link as link_service

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
):
    user_id = _get_user_id(request)
    links = link_service.list_links(
        user_id, start=start, end=end, query=query,
        limit=limit, offset=offset,
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
    user_id = _get_user_id(request)
    results = link_service.request_downloads(req.urls)
    for item in results:
        if item['download_status'] == 'pending':
            link_service.send_download_task(user_id, item['link_id'], item['base_url'])
    return results


@router.post("/delete")
async def delete_link(req: ActivityIdRequest, request: Request):
    user_id = _get_user_id(request)
    success = link_service.delete_link(user_id, req.activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link activity not found")
    return {"ok": True}
