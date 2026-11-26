import asyncio
import os
from pathlib import Path
from typing import List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from agent.vm_command import run_vm_command as _exec
from api.controller.inline import INLINE_BOT_NAME
from storage.service import bot_config as bot_service
from storage.service import link as link_service


router = APIRouter(prefix="/link")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateLinkRequest(BaseModel):
    url: str
    title: Optional[str] = None
    timestamp: Optional[int] = None


class VisitLinkRequest(BaseModel):
    url: str
    title: Optional[str] = None


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
    content: Optional[str] = None
    summary_content_key: Optional[str] = None
    title: Optional[str] = None
    download_status: Optional[str] = None


class TldrRequest(BaseModel):
    link_id: Optional[str] = None
    activity_id: Optional[str] = None
    force: bool = False


class ActivityIdRequest(BaseModel):
    activity_id: str


TLDR_MAX_TOKENS = 2000
TLDR_TIMEOUT = 60.0
S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")
LINK_CONTENT_MAX_BYTES = 5 * 1024 * 1024
TLDR_SYSTEM_PROMPT = (
    "You summarize saved web content for personal knowledge management. "
    "Return concise Markdown with the main points, key details, and any useful caveats. "
    "Do not include preambles."
)
Y_AGENT_HOME = Path(os.environ.get("Y_AGENT_HOME") or "/Users/roy/luohy15").expanduser().resolve()


def _safe_link_key(content_key: str) -> str:
    if not content_key or content_key.startswith(("/", "~")) or ".." in content_key.split("/"):
        raise HTTPException(status_code=400, detail="Invalid content key")
    return content_key


def _vm_content_path(content_key: str) -> str:
    key = _safe_link_key(content_key)
    path = (Y_AGENT_HOME / key).resolve()
    if path != Y_AGENT_HOME and Y_AGENT_HOME not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid content key")
    return str(path)


async def _read_vm_content(user_id: int, content_key: Optional[str]) -> Optional[str]:
    if not content_key:
        return None
    path = _vm_content_path(content_key)
    try:
        return await _exec(user_id, ["bash", "-lc", "cat \"$1\"", "_", path], timeout=30, work_dir=None)
    except Exception:
        return None


class _LinkObjectMissing(Exception):
    pass


class _LinkObjectUnavailable(Exception):
    pass


def _is_s3_link_key(content_key: Optional[str]) -> bool:
    """Legacy lifelog/link/ keys and per-tenant lifelog/<user>/link/ keys are S3 objects."""
    from storage.crypto.blob import is_link_object_key
    return is_link_object_key(content_key)


def _encode_link_body(content: str) -> bytes:
    body = content.encode("utf-8")
    if len(body) > LINK_CONTENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Link content exceeds the 5 MB limit")
    return body


def _read_s3_text(key: str) -> str:
    if not S3_BUCKET:
        raise _LinkObjectUnavailable()
    try:
        from storage.crypto.blob import open_body
        obj = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=key)
        return open_body(key, obj["Body"].read()).decode("utf-8")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise _LinkObjectMissing() from exc
        raise _LinkObjectUnavailable() from exc
    except (BotoCoreError, UnicodeDecodeError) as exc:
        raise _LinkObjectUnavailable() from exc


def _put_s3_bytes(key: str, body: bytes) -> None:
    if not S3_BUCKET:
        raise _LinkObjectUnavailable()
    try:
        from storage.crypto.blob import seal_body
        boto3.client("s3").put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=seal_body(key, body),
            ContentType="text/markdown; charset=utf-8",
        )
    except (ClientError, BotoCoreError) as exc:
        raise _LinkObjectUnavailable() from exc


async def _read_link_content(user_id: int, content_key: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (text, status). status is "missing" only for an absent S3 object."""
    if not content_key:
        return None, None
    if not _is_s3_link_key(content_key):
        return await _read_vm_content(user_id, content_key), None
    try:
        text = await asyncio.to_thread(_read_s3_text, content_key)
    except _LinkObjectMissing:
        return None, "missing"
    except _LinkObjectUnavailable as exc:
        raise HTTPException(status_code=503, detail="Link content is temporarily unavailable") from exc
    return text, None


async def _put_link_object(key: str, content: str) -> None:
    if not _is_s3_link_key(key):
        raise HTTPException(status_code=400, detail="Invalid content key")
    body = _encode_link_body(content)
    try:
        await asyncio.to_thread(_put_s3_bytes, key, body)
    except _LinkObjectUnavailable as exc:
        raise HTTPException(status_code=503, detail="Link content storage is temporarily unavailable") from exc


def _s3_uri(key: str) -> str:
    return f"s3://{S3_BUCKET}/{key}"


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
    tag: Optional[str] = Query(None),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
    tz: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    activity_ids = None
    if todo_id:
        from storage.service.link_todo_relation import list_by_todo
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
        downloaded=downloaded,
        source_feed_id=source_feed_id,
        source=source,
        tag=tag,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
        tz=tz,
    )
    return [link.to_dict() for link in links]


@router.post("")
async def create_link(req: CreateLinkRequest, request: Request):
    user_id = _get_user_id(request)
    link = link_service.add_link(user_id, req.url, title=req.title, timestamp=req.timestamp)
    return link.to_dict()


@router.post("/visit")
async def visit_link(req: VisitLinkRequest, request: Request):
    """Record an interactive `y link fetch` visit (third visit channel, source='fetch')."""
    user_id = _get_user_id(request)
    import time
    link = link_service.add_link_fetch(user_id, req.url, req.title, int(time.time() * 1000))
    return {"link_id": link.link_id, "activity_id": link.activity_id, "base_url": link.base_url}


@router.post("/batch")
async def batch_create_links(req: BatchCreateLinksRequest, request: Request):
    user_id = _get_user_id(request)
    count = link_service.add_links_batch(user_id, [link.model_dump() for link in req.links])
    return {"count": count}


@router.post("/download")
async def download_links(req: DownloadLinksRequest, request: Request):
    user_id = _get_user_id(request)
    results = link_service.request_downloads(req.urls, user_id)
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
        content_key = link_service.build_content_key(link.link_id, user_id=user_id)
        await _put_link_object(content_key, req.content)
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
    requested_activity_id = req.activity_id
    if not link_id:
        if req.url:
            import time
            link = link_service.add_link(user_id, req.url, title=req.title, timestamp=int(time.time() * 1000))
            link_id = link.link_id
            activity_id = activity_id or link.activity_id
        else:
            raise HTTPException(status_code=400, detail="link_id or url required")
    wrote_key = None
    if req.content is not None:
        wrote_key = link_service.build_content_key(link_id, requested_activity_id, user_id=user_id)
        await _put_link_object(wrote_key, req.content)
        link_service.update_download_status(
            link_id, req.download_status or "done", content_key=wrote_key, url=req.url,
        )
    elif req.content_key or req.download_status:
        link_service.update_download_status(link_id, req.download_status or "done", content_key=req.content_key, url=req.url)
    if req.summary_content_key:
        target = activity_id if activity_id else link_id
        link_service.update_summary_content_key(target, req.summary_content_key, is_activity=bool(activity_id))
    if req.title:
        link_service.update_link_title(link_id, req.title)
    if activity_id:
        updated = link_service.get_link(user_id, activity_id)
        payload = updated.to_dict() if updated else {"link_id": link_id, "activity_id": activity_id}
    else:
        entity = link_service.get_link_by_id(link_id)
        payload = {
            "link_id": entity.link_id if entity else link_id,
            "base_url": entity.base_url if entity else None,
            "title": entity.title if entity else req.title,
            "download_status": entity.download_status if entity else req.download_status,
            "content_key": entity.content_key if entity else req.content_key,
            "summary_content_key": entity.summary_content_key if entity else req.summary_content_key,
        }
    if wrote_key:
        payload["content_key"] = wrote_key
        payload["s3_uri"] = _s3_uri(wrote_key)
    return payload


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
            "summary": (await _read_link_content(user_id, existing_key))[0],
            "skipped": True,
        }

    content_key = result.get("content_key")
    content, _content_status = await _read_link_content(user_id, content_key)
    if not content:
        raise HTTPException(status_code=400, detail="Link content is not available")

    summary = await _call_tldr_bot(user_id, content, result.get("title"), result.get("url") or result.get("base_url"))
    if req.activity_id:
        summary_key = link_service.build_summary_key(result["link_id"], req.activity_id, user_id=user_id)
        await _put_link_object(summary_key, summary)
        link_service.update_summary_content_key(req.activity_id, summary_key, is_activity=True)
    else:
        summary_key = link_service.build_summary_key(result["link_id"], user_id=user_id)
        await _put_link_object(summary_key, summary)
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

    content, content_status = await _read_link_content(user_id, result.get("content_key"))
    summary, _summary_status = await _read_link_content(user_id, result.get("summary_content_key"))
    result["content"] = content
    result["summary"] = summary
    if content_status:
        result["content_status"] = content_status
    return result


@router.get("/resolve")
async def resolve_url(request: Request, url: str = Query(...)):
    user_id = _get_user_id(request)
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    return link_service.resolve_url(user_id, url)


async def _call_tldr_bot(user_id: int, content: str, title: Optional[str], url: Optional[str]) -> str:
    bot_config = bot_service.get_config(user_id, INLINE_BOT_NAME)
    if not bot_config or not bot_config.api_key or not bot_config.model:
        raise HTTPException(
            status_code=502,
            detail=f"Bot {INLINE_BOT_NAME!r} is not configured for this user (api_key and model required)",
        )

    user_content = "\n".join([
        f"Title: {title or ''}",
        f"URL: {url or ''}",
        "",
        "Content:",
        content,
    ])
    from agent.openai_chat import openai_chat_completion
    try:
        result, _ = await openai_chat_completion(
            [{"role": "user", "content": user_content}],
            bot_config,
            max_tokens=bot_config.max_tokens or TLDR_MAX_TOKENS,
            system_prompt=TLDR_SYSTEM_PROMPT,
            timeout=TLDR_TIMEOUT,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}") from e
    return (result or "").strip()


@router.post("/delete")
async def delete_link(req: ActivityIdRequest, request: Request):
    user_id = _get_user_id(request)
    success = link_service.delete_link(user_id, req.activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link activity not found")
    return {"ok": True}
