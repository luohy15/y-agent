"""Terminal endpoint — run commands via local_exec/ssh_exec."""

import dataclasses

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/terminal")


@router.post("/run")
async def run_command(request: Request, vm_name: str = Query(None), work_dir: str = Query(None)):
    user_id = request.state.user_id
    body = await request.json()
    cmd = body.get("command", "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    from agent.config import resolve_vm_config
    from agent.vm_command import execute_vm_command
    vm_config = resolve_vm_config(user_id, vm_name)
    if work_dir:
        vm_config = dataclasses.replace(vm_config, work_dir=work_dir)

    try:
        result = await execute_vm_command(vm_config, ["bash", "-c", cmd], timeout=300)
        return {"output": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
