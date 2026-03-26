from fastapi import APIRouter, Query, Request

from api.controller.file import _exec

router = APIRouter(prefix="/git")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/status")
async def git_status(request: Request, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    output = await _exec(user_id, ["git", "status", "--porcelain"], vm_name=vm_name, work_dir=work_dir)
    files = []
    for line in output.strip().splitlines():
        if not line or len(line) < 3:
            continue
        # Porcelain format: XY<space>path, but _exec may strip leading spaces
        # so split on first space to reliably extract path
        status_part = line[:2]
        rest = line[2:].lstrip(" ")
        status = status_part.strip()
        if not status or not rest:
            continue
        # Handle renames: "R  old -> new"
        if " -> " in rest:
            rest = rest.split(" -> ")[-1]
        # Expand untracked directories into individual files
        if status == "??" and rest.endswith("/"):
            try:
                dir_files = await _exec(
                    user_id, ["find", rest, "-type", "f"],
                    vm_name=vm_name, work_dir=work_dir
                )
                for f in dir_files.strip().splitlines():
                    f = f.strip()
                    if f:
                        files.append({"status": status, "path": f})
            except Exception:
                files.append({"status": status, "path": rest})
        else:
            files.append({"status": status, "path": rest})
    return {"files": files}


@router.get("/diff")
async def git_diff(request: Request, path: str = Query(...), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    # Try staged diff first, fall back to unstaged, then show new file
    diff = await _exec(user_id, ["git", "diff", "-U99999", "--cached", "--", path], vm_name=vm_name, work_dir=work_dir)
    if not diff.strip():
        diff = await _exec(user_id, ["git", "diff", "-U99999", "--", path], vm_name=vm_name, work_dir=work_dir)
    if not diff.strip():
        # Untracked file — show full content as added
        content = await _exec(user_id, ["cat", path], vm_name=vm_name, work_dir=work_dir)
        lines = content.split("\n")
        diff = f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        diff += "\n".join(f"+{line}" for line in lines)
    return {"path": path, "diff": diff}


@router.post("/discard")
async def git_discard(request: Request, path: str = Query(...), vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = _get_user_id(request)
    # Check if the file is untracked
    output = await _exec(user_id, ["git", "status", "--porcelain", "--", path], vm_name=vm_name, work_dir=work_dir)
    status = output.strip()[:2] if output.strip() else ""
    if status.strip() == "??":
        # Untracked file — remove it
        await _exec(user_id, ["rm", "-f", path], vm_name=vm_name, work_dir=work_dir)
    else:
        # Tracked file — restore it
        await _exec(user_id, ["git", "checkout", "--", path], vm_name=vm_name, work_dir=work_dir)
        # Also unstage if staged
        await _exec(user_id, ["git", "reset", "HEAD", "--", path], vm_name=vm_name, work_dir=work_dir)
    return {"ok": True}
