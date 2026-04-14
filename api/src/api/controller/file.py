import asyncio
import base64
import dataclasses
import fnmatch
import json
import mimetypes
import os

from loguru import logger

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
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

async def _exec(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None, work_dir: str = None) -> str:
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
    runner = _CmdRunner(vm_config)
    return await runner.run_cmd(cmd, timeout=timeout)


async def _get_vscode_excludes(user_id: int, vm_name: str, key: str, work_dir: str = None) -> list[str]:
    try:
        raw = await _exec(user_id, ["cat", ".vscode/settings.json"], vm_name=vm_name, work_dir=work_dir)
        settings = json.loads(raw)
        excludes = settings.get(key, {})
        return [pat.removeprefix("**/") for pat, enabled in excludes.items() if enabled is True]
    except Exception:
        return []


@router.get("/list")
async def list_files(request: Request, path: str = Query("."), vm_name: str = Query(None), work_dir: str = Query(None), sort: str = Query(None)):
    user_id = _get_user_id(request)
    excludes = await _get_vscode_excludes(user_id, vm_name, "files.exclude", work_dir=work_dir)
    logger.info("list_files excludes: {}", excludes)
    if sort == "atime":
        # Use find -printf to get atime as epoch + filename, sorted descending
        stat_cmd = ["bash", "-c", f"find {path} -maxdepth 1 -type f -printf '%A@\\t%f\\n' | sort -rn"]
        output = await _exec(user_id, stat_cmd, vm_name=vm_name, work_dir=work_dir)
        entries = []
        for line in output.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            atime_str, name = parts
            if any(fnmatch.fnmatch(name, pat) for pat in excludes):
                continue
            try:
                atime = int(float(atime_str))
            except ValueError:
                atime = None
            entries.append({"name": name, "type": "file", "atime": atime})
        return {"path": path, "entries": entries}

    # ls -1apL: one per line, show dirs with /, show hidden, dereference symlinks
    ls_cmd = ["ls", "-1apL", path]
    output = await _exec(user_id, ls_cmd, vm_name=vm_name, work_dir=work_dir)
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
async def read_file(request: Request, path: str = Query(...), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    content = await _exec(user_id, ["cat", path], vm_name=vm_name, work_dir=work_dir)
    return {"path": path, "content": content}


async def _exec_bytes(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None, work_dir: str = None) -> bytes:
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
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
    b64 = await _exec(user_id, ["base64", cmd[-1]], timeout=timeout, vm_name=vm_name, work_dir=work_dir)
    return base64.b64decode(b64)


@router.get("/search")
async def search_files(request: Request, q: str = Query(...), path: str = Query("."), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    excludes = await _get_vscode_excludes(user_id, vm_name, "search.exclude", work_dir=work_dir)
    # Build find command with exclude args from vscode settings
    find_cmd = ["find", path, "-maxdepth", "8", "-type", "f"]
    for pat in excludes:
        find_cmd += ["-not", "-path", f"*/{pat}/*" if not pat.startswith("*") else pat]
    find_cmd += ["-iname", f"*{q}*"]
    logger.info("search_files cmd: {}", find_cmd)
    output = await _exec(user_id, find_cmd, timeout=10, vm_name=vm_name, work_dir=work_dir)
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
async def move_files(request: Request, body: MoveRequest, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    await _exec(user_id, ["mv", *body.sources, body.dest_dir], vm_name=vm_name, work_dir=work_dir)
    return {"sources": body.sources, "dest_dir": body.dest_dir, "success": True}


_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    dest_dir: str = Form(...),
    vm_name: str = Form(None),
    work_dir: str = Form(None),
):
    user_id = _get_user_id(request)
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    filename = os.path.basename(file.filename or "upload")
    dest_path = f"{dest_dir}/{filename}"

    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
    if not vm_config.api_token:
        # Local: write directly to disk
        effective_dir = os.path.expanduser(vm_config.work_dir) if vm_config.work_dir else "."
        full_path = os.path.normpath(os.path.join(effective_dir, dest_path))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)
    else:
        # Remote: pipe base64-encoded content through stdin and decode on target
        import shlex
        b64 = base64.b64encode(content).decode("ascii")
        runner = _CmdRunner(vm_config)
        await runner.run_cmd(["bash", "-c", f"base64 -d > {shlex.quote(dest_path)}"], stdin=b64)

    return {"path": dest_path, "size": len(content), "success": True}


@router.get("/raw")
async def raw_file(request: Request, path: str = Query(...), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    data = await _exec_bytes(user_id, ["cat", path], timeout=30, vm_name=vm_name, work_dir=work_dir)
    mime, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime or "application/octet-stream")
