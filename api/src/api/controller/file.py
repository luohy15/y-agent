import asyncio
import fnmatch
import json
import mimetypes
import os

from loguru import logger

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from agent.config import resolve_vm_config
from agent.tool_base import Tool

router = APIRouter(prefix="/file")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}
    async def execute(self, arguments):
        pass

async def _exec(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None) -> str:
    vm_config = resolve_vm_config(user_id, vm_name)
    runner = _CmdRunner(vm_config)
    return await runner.run_cmd(cmd, timeout=timeout)


async def _get_vscode_excludes(user_id: int, vm_name: str, key: str) -> list[str]:
    try:
        raw = await _exec(user_id, ["cat", ".vscode/settings.json"], vm_name=vm_name)
        settings = json.loads(raw)
        excludes = settings.get(key, {})
        return [pat.removeprefix("**/") for pat, enabled in excludes.items() if enabled is True]
    except Exception:
        return []


@router.get("/list")
async def list_files(request: Request, path: str = Query("."), vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    excludes = await _get_vscode_excludes(user_id, vm_name, "files.exclude")
    logger.info("list_files excludes: {}", excludes)
    # ls -1apL: one per line, show dirs with /, show hidden, dereference symlinks
    output = await _exec(user_id, ["ls", "-1apL", path], vm_name=vm_name)
    entries = []
    for line in output.strip().splitlines():
        if not line or line == "./" or line == "../":
            continue
        # Skip entries with control characters (non-printable)
        if any(c < ' ' or c == '\x7f' for c in line.rstrip("/")):
            continue
        name = line[:-1] if line.endswith("/") else line
        if any(fnmatch.fnmatch(name, pat) for pat in excludes):
            continue
        if line.endswith("/"):
            entries.append({"name": name, "type": "directory"})
        else:
            entries.append({"name": name, "type": "file"})
    return {"path": path, "entries": entries}


@router.get("/read")
async def read_file(request: Request, path: str = Query(...), vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    content = await _exec(user_id, ["cat", path], vm_name=vm_name)
    return {"path": path, "content": content}


async def _exec_bytes(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None) -> bytes:
    vm_config = resolve_vm_config(user_id, vm_name)
    if not vm_config.api_token:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.path.expanduser(vm_config.work_dir) if vm_config.work_dir else None,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout or b""
    # For remote VMs, read via base64 encoding
    import base64
    b64 = await _exec(user_id, ["base64", cmd[-1]], timeout=timeout, vm_name=vm_name)
    return base64.b64decode(b64)


@router.get("/search")
async def search_files(request: Request, q: str = Query(...), path: str = Query("."), vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    excludes = await _get_vscode_excludes(user_id, vm_name, "search.exclude")
    # Build find command with exclude args from vscode settings
    find_cmd = ["find", path, "-maxdepth", "8", "-type", "f"]
    for pat in excludes:
        find_cmd += ["-not", "-path", f"*/{pat}/*" if not pat.startswith("*") else pat]
    find_cmd += ["-iname", f"*{q}*"]
    logger.info("search_files cmd: {}", find_cmd)
    output = await _exec(user_id, find_cmd, timeout=10, vm_name=vm_name)
    files = []
    for line in output.strip().splitlines():
        if not line or len(files) >= 50:
            continue
        rel = line.removeprefix("./")
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pat) for pat in excludes):
            continue
        files.append(rel)
    return {"query": q, "files": files}


class MoveRequest(BaseModel):
    sources: list[str]
    dest_dir: str


@router.post("/move")
async def move_files(request: Request, body: MoveRequest, vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    await _exec(user_id, ["mv", *body.sources, body.dest_dir], vm_name=vm_name)
    return {"sources": body.sources, "dest_dir": body.dest_dir, "success": True}


@router.get("/raw")
async def raw_file(request: Request, path: str = Query(...), vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    data = await _exec_bytes(user_id, ["cat", path], timeout=30, vm_name=vm_name)
    mime, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime or "application/octet-stream")
