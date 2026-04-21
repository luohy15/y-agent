import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from storage.service import link as link_service

Y_AGENT_HOME = os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


_SSH_READ_HEADER_OK = "__Y_OK__\n"
_SSH_READ_HEADER_MISS = "__Y_MISS__\n"


async def _read_content_remote(user_id: int, content_key: str, timeout: int = 30) -> Optional[str]:
    """Read `${Y_AGENT_HOME:-$HOME/.y-agent}/<content_key>` from the user's remote VM."""
    try:
        vm_config = resolve_vm_config(user_id)
        runner = _CmdRunner(vm_config)
        safe_path = content_key.replace("'", "'\\''")
        script = (
            f'target="${{Y_AGENT_HOME:-$HOME/.y-agent}}/{safe_path}"; '
            f'if [ -f "$target" ]; then printf %s "{_SSH_READ_HEADER_OK}"; cat "$target"; '
            f'else printf %s "{_SSH_READ_HEADER_MISS}"; fi'
        )
        out = await runner.run_cmd(["sh", "-c", script], timeout=timeout)
    except Exception as e:
        logger.warning("ssh read_content err key={}: {}", content_key, e)
        return None
    if out.startswith(_SSH_READ_HEADER_OK):
        return out[len(_SSH_READ_HEADER_OK):]
    return None

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
            link_service.send_download_task(user_id, item['link_id'], item['url'], activity_id=item.get('activity_id'))
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
        full_path = os.path.join(Y_AGENT_HOME, content_key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(req.content)
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
    if content_key:
        result["content"] = await _read_link_content(user_id, content_key)
    else:
        result["content"] = None

    return result


async def _read_link_content(user_id: int, content_key: str) -> Optional[str]:
    full_path = os.path.join(Y_AGENT_HOME, content_key)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        pass
    return await _read_content_remote(user_id, content_key)


@router.post("/delete")
async def delete_link(req: ActivityIdRequest, request: Request):
    user_id = _get_user_id(request)
    success = link_service.delete_link(user_id, req.activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link activity not found")
    return {"ok": True}
