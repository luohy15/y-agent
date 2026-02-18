import asyncio
import mimetypes
import os

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


@router.get("/list")
async def list_files(request: Request, path: str = Query("."), vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    # ls -1apL: one per line, show dirs with /, show hidden, dereference symlinks
    output = await _exec(user_id, ["ls", "-1apL", path], vm_name=vm_name)
    entries = []
    for line in output.strip().splitlines():
        if not line or line == "./" or line == "../":
            continue
        # Skip entries with control characters (non-printable)
        if any(c < ' ' or c == '\x7f' for c in line.rstrip("/")):
            continue
        if line.endswith("/"):
            entries.append({"name": line[:-1], "type": "directory"})
        else:
            entries.append({"name": line, "type": "file"})
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
    # Use git ls-files to respect .gitignore, fall back to find if not a git repo
    try:
        output = await _exec(
            user_id,
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", path],
            timeout=10,
            vm_name=vm_name,
        )
    except Exception:
        output = ""
    q_lower = q.lower()
    files = []
    for line in output.strip().splitlines():
        if line and q_lower in line.lower() and len(files) < 50:
            files.append(line.removeprefix("./"))
    # Fall back to find if git ls-files returned nothing (not a git repo)
    if not files and not output.strip():
        output = await _exec(
            user_id,
            ["find", path, "-maxdepth", "8", "-type", "f", "-iname", f"*{q}*"],
            timeout=10,
            vm_name=vm_name,
        )
        for line in output.strip().splitlines():
            if line and len(files) < 50:
                files.append(line.removeprefix("./"))
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
