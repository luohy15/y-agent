"""Terminal endpoint — run commands via local_exec/ssh_exec."""

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import resolve_vm_config
from agent.tools.local_exec import local_exec
from agent.tools.ssh_exec import ssh_exec

router = APIRouter(prefix="/terminal")


async def _run_cmd(vm_config, cmd: list[str], timeout: float = 300) -> str:
    work_dir = vm_config.work_dir if vm_config else None
    if not vm_config or not vm_config.api_token:
        return await local_exec(cmd, None, timeout, cwd=work_dir)
    return await ssh_exec(vm_config, cmd, None, dir=work_dir or None, timeout=timeout)


@router.post("/run")
async def run_command(request: Request, vm_name: str = Query(None)):
    user_id = request.state.user_id
    body = await request.json()
    cmd = body.get("command", "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    vm_config = resolve_vm_config(user_id, vm_name)

    try:
        result = await _run_cmd(vm_config, ["bash", "-c", cmd])
        return {"output": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
