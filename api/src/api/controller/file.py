import asyncio
import base64
import dataclasses
import fnmatch
import json
import mimetypes
import os
from pathlib import Path

from loguru import logger

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/file")

Y_AGENT_HOME = Path(os.environ.get("Y_AGENT_HOME") or "/Users/roy/luohy15").expanduser().resolve()


def _get_user_id(request: Request) -> int:
    return request.state.user_id


# Lazily build the Tool subclass so the agent layer (paramiko/cryptography/boto3)
# stays out of the API import path until /file endpoints are actually hit.
_cmd_runner_cls = None


def _get_cmd_runner_cls():
    global _cmd_runner_cls
    if _cmd_runner_cls is None:
        from agent.tool_base import Tool

        class _CmdRunner(Tool):
            name = "_cmd_runner"
            description = ""
            parameters = {}
            async def execute(self, arguments):
                pass

        _cmd_runner_cls = _CmdRunner
    return _cmd_runner_cls


async def _exec(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None, work_dir: str = None) -> str:
    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
    runner = _get_cmd_runner_cls()(vm_config)
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
    if path.startswith("/") or path.startswith("~"):
        work_dir = None
    content = await _exec(user_id, ["cat", path], vm_name=vm_name, work_dir=work_dir)
    return {"path": path, "content": content}


_SKILLS_DIR = "/Users/roy/luohy15/.agents/skills"


@router.get("/skills")
async def list_skills(request: Request, vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    # For each subdir with a SKILL.md, emit "name\tdescription" (description from YAML
    # frontmatter; only the first line, no continuation parsing).
    script = (
        f'for d in {_SKILLS_DIR}/*/; do '
        'name=$(basename "$d"); '
        'f="$d/SKILL.md"; '
        '[ -f "$f" ] || continue; '
        'desc=$(awk \'/^description:/{sub(/^description: */, ""); print; exit}\' "$f"); '
        'printf "%s\\t%s\\n" "$name" "$desc"; '
        'done'
    )
    output = await _exec(user_id, ["bash", "-c", script], vm_name=vm_name, timeout=15)
    skills = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\t", 1)
        name = parts[0]
        description = parts[1] if len(parts) == 2 else ""
        skills.append({
            "name": name,
            "description": description,
            "path": f"{_SKILLS_DIR}/{name}/SKILL.md",
        })
    skills.sort(key=lambda s: s["name"])
    return {"skills": skills}


async def _exec_bytes(user_id: int, cmd: list[str], timeout: float = 10, vm_name: str = None, work_dir: str = None) -> bytes:
    from agent.config import resolve_vm_config
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


class TouchRequest(BaseModel):
    path: str


@router.post("/touch")
async def touch_file(request: Request, body: TouchRequest, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    await _exec(user_id, ["touch", "-a", body.path], vm_name=vm_name, work_dir=work_dir)
    return {"path": body.path, "success": True}


class DeleteRequest(BaseModel):
    path: str


_SAFE_UNLINK_SCRIPT = r"""
import json
import os
import stat
import sys


def emit(status, detail=""):
    print(json.dumps({"status": status, "detail": detail}))


requested_path = sys.argv[1] if len(sys.argv) > 1 else ""
if not requested_path or "\0" in requested_path:
    emit("invalid", "Path must not be empty or contain NUL bytes")
    raise SystemExit

agent_home = sys.argv[2] if len(sys.argv) > 2 else ""
if not agent_home:
    emit("invalid", "Y_AGENT_HOME is not configured")
    raise SystemExit

root = os.path.realpath(os.path.expanduser(agent_home))
candidate = requested_path if os.path.isabs(requested_path) else os.path.join(os.getcwd(), requested_path)
candidate = os.path.normpath(candidate)
if candidate == root:
    emit("unsupported", "Y_AGENT_HOME cannot be deleted")
    raise SystemExit
parent = os.path.realpath(os.path.dirname(candidate))

try:
    inside_root = os.path.commonpath([root, parent]) == root
except ValueError:
    inside_root = False
if not inside_root:
    emit("invalid", "Path is outside Y_AGENT_HOME")
    raise SystemExit

entry = os.path.join(parent, os.path.basename(candidate))
try:
    entry_stat = os.lstat(entry)
except FileNotFoundError:
    emit("missing", "File does not exist")
    raise SystemExit
except OSError as exc:
    emit("error", str(exc))
    raise SystemExit

if stat.S_ISDIR(entry_stat.st_mode):
    emit("unsupported", "Directories cannot be deleted")
    raise SystemExit
if not (stat.S_ISREG(entry_stat.st_mode) or stat.S_ISLNK(entry_stat.st_mode)):
    emit("unsupported", "Only files and symlinks can be deleted")
    raise SystemExit

try:
    os.unlink(entry)
except FileNotFoundError:
    emit("missing", "File does not exist")
except OSError as exc:
    emit("error", str(exc))
else:
    emit("deleted")
"""


@router.post("/delete")
async def delete_file(request: Request, body: DeleteRequest, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    try:
        output = await _exec(
            user_id,
            ["python3", "-c", _SAFE_UNLINK_SCRIPT, body.path, str(Y_AGENT_HOME)],
            vm_name=vm_name,
            work_dir=work_dir,
        )
        result = json.loads(output.strip())
    except Exception as exc:
        logger.exception("safe delete failed")
        raise HTTPException(status_code=500, detail="Unable to delete file") from exc

    status = result.get("status")
    detail = result.get("detail") or "Unable to delete file"
    if status == "deleted":
        return {"path": body.path, "deleted": True}
    if status == "invalid":
        raise HTTPException(status_code=400, detail=detail)
    if status == "missing":
        raise HTTPException(status_code=404, detail=detail)
    if status == "unsupported":
        raise HTTPException(status_code=409, detail=detail)
    raise HTTPException(status_code=500, detail=detail)


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

    from agent.config import resolve_vm_config
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
        runner = _get_cmd_runner_cls()(vm_config)
        await runner.run_cmd(["bash", "-c", f"base64 -d > {shlex.quote(dest_path)}"], stdin=b64)

    return {"path": dest_path, "size": len(content), "success": True}


class WriteRequest(BaseModel):
    path: str
    content: str


@router.post("/write")
async def write_file(request: Request, body: WriteRequest, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
    if not vm_config.api_token:
        # Local: write directly to disk
        effective_dir = os.path.expanduser(vm_config.work_dir) if vm_config.work_dir else "."
        full_path = os.path.normpath(os.path.join(effective_dir, body.path))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(body.content)
    else:
        # Remote: pipe base64-encoded content through stdin and decode on target
        import shlex
        b64 = base64.b64encode(body.content.encode("utf-8")).decode("ascii")
        runner = _get_cmd_runner_cls()(vm_config)
        await runner.run_cmd(["bash", "-c", f"base64 -d > {shlex.quote(body.path)}"], stdin=b64)
    return {"path": body.path, "success": True}


@router.get("/raw")
async def raw_file(request: Request, path: str = Query(...), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    if path.startswith("/") or path.startswith("~"):
        work_dir = None
    data = await _exec_bytes(user_id, ["cat", path], timeout=30, vm_name=vm_name, work_dir=work_dir)
    mime, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime or "application/octet-stream")


# --- PDF export (server-side WeasyPrint render) -------------------------------
#
# The standalone HTML (built client-side by buildHtmlDocument) is rendered to PDF
# on the resolved VM through the same exec channel as every other file op. The
# HTML arrives on stdin; WeasyPrint derives a real PDF /Outlines dictionary from
# the heading structure (its UA stylesheet sets bookmark-level on h1-h6), which
# is what macOS Preview's sidebar reads. Only base64 (success) or a
# "__PDF_ERR__:" sentinel (failure) is ever written to stdout, so the
# merged-stderr local transport can't corrupt the payload; WeasyPrint's own
# stderr/warnings are captured to a temp log and dropped. base64's alphabet never
# contains '_', so the sentinel is unambiguous.
_WEASYPRINT_RENDER_SCRIPT = r"""
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
if ! command -v weasyprint >/dev/null 2>&1; then echo "__PDF_ERR__:renderer_missing"; exit 0; fi
d=$(mktemp -d) || { echo "__PDF_ERR__:render_failed:no_tmpdir"; exit 0; }
trap 'rm -rf "$d"' EXIT
if weasyprint - "$d/out.pdf" >"$d/log" 2>&1; then
  base64 "$d/out.pdf"
else
  printf '__PDF_ERR__:render_failed:'
  tail -c 400 "$d/log" 2>/dev/null | tr -d '\r' | tr '\n' ' '
fi
"""


class ExportPdfRequest(BaseModel):
    html: str
    filename: str | None = None


def _pdf_content_disposition(filename: str | None) -> str:
    import re
    from urllib.parse import quote
    # basename, drop control chars / quotes that would break the header value,
    # strip one trailing extension, force .pdf (mirrors the client's exportFilename)
    name = os.path.basename((filename or "").strip())
    name = "".join(c for c in name if c >= " " and c not in '"\\')
    stem = (re.sub(r"\.[^.]*$", "", name) or name).strip() or "export"
    full = f"{stem}.pdf"
    ascii_stem = stem.encode("ascii", "ignore").decode().strip()
    ascii_full = f"{ascii_stem}.pdf" if ascii_stem else "export.pdf"
    return f"attachment; filename=\"{ascii_full}\"; filename*=UTF-8''{quote(full)}"


@router.post("/export-pdf")
async def export_pdf(request: Request, body: ExportPdfRequest, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    if not body.html or not body.html.strip():
        raise HTTPException(status_code=400, detail="Missing HTML payload")

    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)
    runner = _get_cmd_runner_cls()(vm_config)
    try:
        output = await runner.run_cmd(
            ["bash", "-c", _WEASYPRINT_RENDER_SCRIPT], stdin=body.html, timeout=60
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="PDF render timed out")

    if output.startswith("__PDF_ERR__:renderer_missing"):
        raise HTTPException(status_code=503, detail="PDF renderer (WeasyPrint) is not installed on the render host")
    if output.startswith("__PDF_ERR__:render_failed"):
        reason = output.split("render_failed:", 1)[-1].strip() or "unknown error"
        raise HTTPException(status_code=502, detail=f"PDF render failed: {reason[:300]}")
    try:
        pdf = base64.b64decode(output)
    except Exception:
        raise HTTPException(status_code=502, detail="PDF render produced invalid output")
    if pdf[:5] != b"%PDF-":
        raise HTTPException(status_code=502, detail="PDF render produced no output")

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _pdf_content_disposition(body.filename)},
    )
