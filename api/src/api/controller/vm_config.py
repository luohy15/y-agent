from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from agent.config import resolve_vm_config
from storage.entity.dto import VmConfig
from storage.service import vm_config as vm_service

router = APIRouter(prefix="/vm-config")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class VmConfigRequest(BaseModel):
    name: str = "default"
    api_token: str = ""
    vm_name: str = ""
    work_dir: str = ""


@router.get("/list")
async def list_vm_configs(request: Request):
    user_id = _get_user_id(request)
    configs = vm_service.list_configs(user_id)
    if not configs:
        default = resolve_vm_config(user_id)
        configs = [default]
    return [
        {"name": c.name, "vm_name": c.vm_name, "work_dir": c.work_dir}
        for c in configs
    ]


@router.post("")
async def set_vm_config(req: VmConfigRequest, request: Request):
    user_id = _get_user_id(request)
    config = VmConfig(
        name=req.name,
        api_token=req.api_token,
        vm_name=req.vm_name,
        work_dir=req.work_dir,
    )
    vm_service.set_config(user_id, config)
    return {"ok": True}


@router.delete("")
async def delete_vm_config(request: Request, name: str = Query("default")):
    user_id = _get_user_id(request)
    deleted = vm_service.delete_config(user_id, name)
    return {"ok": True, "deleted": deleted}
