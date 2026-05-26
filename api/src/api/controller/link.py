import base64
import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.controller.file import _exec
from storage.service import bot_config as bot_service
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


class CreatePageLinkRequest(BaseModel):
    path: str
    title: Optional[str] = None
    content: Optional[str] = None


class LinkContentMetaRequest(BaseModel):
    url: Optional[str] = None
    link_id: Optional[str] = None
    activity_id: Optional[str] = None
    content_key: Optional[str] = None
    summary_content_key: Optional[str] = None
    title: Optional[str] = None
    download_status: Optional[str] = None


class TldrRequest(BaseModel):
    link_id: Optional[str] = None
    activity_id: Optional[str] = None
    force: bool = False


class ActivityIdRequest(BaseModel):
    activity_id: str


TLDR_BOT_NAME = "tldr"
TLDR_MAX_TOKENS = 2000
TLDR_TIMEOUT = 60.0
TLDR_SYSTEM_PROMPT = (
    "You summarize saved web content for personal knowledge management. "
    "Return concise Markdown with the main points, key details, and any useful caveats. "
    "Do not include preambles."
)


def _safe_link_key(content_key: str) -> str:
    if not content_key or content_key.startswith(("/", "~")) or ".." in content_key.split("/"):
        raise HTTPException(status_code=400, detail="Invalid content key")
    return content_key


async def _read_vm_content(user_id: int, content_key: Optional[str]) -> Optional[str]:
    if not content_key:
        return None
    key = _safe_link_key(content_key)
    try:
        return await _exec(user_id, ["bash", "-lc", "cat \"$HOME/luohy15/$1\"", "_", key], timeout=30, work_dir=None)
    except Exception:
        return None


async def _write_vm_content(user_id: int, content_key: str, content: str) -> None:
    key = _safe_link_key(content_key)
    payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
    script = "path=\"$HOME/luohy15/$1\"; mkdir -p \"$(dirname \"$path\")\" && printf '%s' \"$2\" | base64 -d > \"$path\""
    await _exec(user_id, ["bash", "-lc", script, "_", key, payload], timeout=60, work_dir=None)


@router.get("/list")
async def list_links(
    request: Request,
    query: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    todo_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    downloaded: Optional[bool] = Query(None),
    source_feed_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    activity_ids = None
    if todo_id:
        from storage.repository.link_todo_relation import list_by_todo
        activity_ids = list_by_todo(user_id, todo_id)
        if not activity_ids:
            return []
    elif entity_id:
        from storage.repository.entity_link_relation import list_by_entity
        activity_ids = list_by_entity(user_id, entity_id)
        if not activity_ids:
            return []
    links = link_service.list_links(
        user_id, query=query,
        limit=limit, offset=offset, activity_ids=activity_ids,
        downloaded_only=bool(downloaded),
        source_feed_id=source_feed_id,
        source=source,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )
    return [l.to_dict() for l in links]


@router.post("")
async def create_link(req: CreateLinkRequest, request: Request):
    user_id = _get_user_id(request)
    link = link_service.add_link(user_id, req.url, title=req.title, timestamp=req.timestamp)
    return link.to_dict()


@router.post("/batch")
async def batch_create_links(req: BatchCreateLinksRequest, request: Request):
    user_id = _get_user_id(request)
    count = link_service.add_links_batch(user_id, [l.model_dump() for l in req.links])
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
        await _write_vm_content(user_id, content_key, req.content)
        link_service.update_download_status(link.link_id, "done", content_key=content_key)
    else:
        link_service.update_download_status(link.link_id, "done", content_key=req.path)
    updated = link_service.get_link(user_id, link.activity_id)
    return updated.to_dict()


@router.post("/content-meta")
async def save_link_content_meta(req: LinkContentMetaRequest, request: Request):
    user_id = _get_user_id(request)
    link_id = req.link_id
    activity_id = req.activity_id
    if not link_id:
        if req.url:
            import time
            link = link_service.add_link(user_id, req.url, title=req.title, timestamp=int(time.time() * 1000))
            link_id = link.link_id
            activity_id = activity_id or link.activity_id
        else:
            raise HTTPException(status_code=400, detail="link_id or url required")
    if req.content_key or req.download_status:
        link_service.update_download_status(link_id, req.download_status or "done", content_key=req.content_key, url=req.url)
    if req.summary_content_key:
        target = activity_id if activity_id else link_id
        link_service.update_summary_content_key(target, req.summary_content_key, is_activity=bool(activity_id))
    if req.title:
        link_service.update_link_title(link_id, req.title)
    if activity_id:
        updated = link_service.get_link(user_id, activity_id)
        return updated.to_dict() if updated else {"link_id": link_id, "activity_id": activity_id}
    entity = link_service.get_link_by_id(link_id)
    return {
        "link_id": entity.link_id if entity else link_id,
        "base_url": entity.base_url if entity else None,
        "title": entity.title if entity else req.title,
        "download_status": entity.download_status if entity else req.download_status,
        "content_key": entity.content_key if entity else req.content_key,
        "summary_content_key": entity.summary_content_key if entity else req.summary_content_key,
    }


@router.post("/tldr")
async def generate_link_tldr(req: TldrRequest, request: Request):
    user_id = _get_user_id(request)
    if bool(req.link_id) == bool(req.activity_id):
        raise HTTPException(status_code=400, detail="Exactly one of link_id or activity_id required")

    link = link_service.get_link(user_id, req.activity_id) if req.activity_id else link_service.get_link_by_id(req.link_id or "")
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    result = link.to_dict() if hasattr(link, "to_dict") else {
        "link_id": link.link_id,
        "base_url": link.base_url,
        "title": link.title,
        "download_status": link.download_status,
        "content_key": link.content_key,
        "summary_content_key": link.summary_content_key,
    }
    existing_key = result.get("summary_content_key")
    if existing_key and not req.force:
        return {
            "link_id": result.get("link_id"),
            "activity_id": req.activity_id,
            "summary_content_key": existing_key,
            "summary": await _read_vm_content(user_id, existing_key),
            "skipped": True,
        }

    content_key = result.get("content_key")
    content = await _read_vm_content(user_id, content_key)
    if not content:
        raise HTTPException(status_code=400, detail="Link content is not available on VM")

    summary = await _call_tldr_bot(user_id, content, result.get("title"), result.get("url") or result.get("base_url"))
    if req.activity_id:
        summary_key = f"links/{result['link_id']}/{req.activity_id}/summary.md"
        await _write_vm_content(user_id, summary_key, summary)
        link_service.update_summary_content_key(req.activity_id, summary_key, is_activity=True)
    else:
        summary_key = f"links/{result['link_id']}/summary.md"
        await _write_vm_content(user_id, summary_key, summary)
        link_service.update_summary_content_key(result["link_id"], summary_key, is_activity=False)
    return {
        "link_id": result.get("link_id"),
        "activity_id": req.activity_id,
        "summary_content_key": summary_key,
        "summary": summary,
        "skipped": False,
    }


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
        "summary_content_key": link.summary_content_key,
    }

    result["content"] = await _read_vm_content(user_id, result.get("content_key"))
    result["summary"] = await _read_vm_content(user_id, result.get("summary_content_key"))
    return result


@router.get("/resolve")
async def resolve_url(request: Request, url: str = Query(...)):
    user_id = _get_user_id(request)
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    return link_service.resolve_url(user_id, url)


async def _call_tldr_bot(user_id: int, content: str, title: Optional[str], url: Optional[str]) -> str:
    bot_config = bot_service.get_config(user_id, TLDR_BOT_NAME)
    if not bot_config or not bot_config.api_key or not bot_config.model:
        raise HTTPException(
            status_code=502,
            detail=f"Bot {TLDR_BOT_NAME!r} is not configured for this user (api_key and model required)",
        )

    user_content = "\n".join([
        f"Title: {title or ''}",
        f"URL: {url or ''}",
        "",
        "Content:",
        content,
    ])
    payload = {
        "model": bot_config.model,
        "max_tokens": bot_config.max_tokens or TLDR_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": TLDR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    if bot_config.openrouter_config:
        payload["provider"] = bot_config.openrouter_config.get("provider", bot_config.openrouter_config)

    api_path = bot_config.custom_api_path or "/chat/completions"
    url_endpoint = f"{bot_config.base_url.rstrip('/')}/{api_path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {bot_config.api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TLDR_TIMEOUT) as client:
            resp = await client.post(url_endpoint, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"LLM error {resp.status_code}: {resp.text}")
    data = resp.json()
    try:
        result = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail=f"Unexpected LLM response: {data}")
    return (result or "").strip()


@router.post("/delete")
async def delete_link(req: ActivityIdRequest, request: Request):
    user_id = _get_user_id(request)
    success = link_service.delete_link(user_id, req.activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link activity not found")
    return {"ok": True}
