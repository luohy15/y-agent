from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional

from storage.entity.dto import VmConfig
from storage.service import vm_config as vm_service

router = APIRouter(prefix="/vm-config")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class VmConfigRequest(BaseModel):
    name: str
    # None means "omitted": keep the stored key. "" explicitly inherits the
    # default node's key.
    api_token: Optional[str] = None
    vm_name: str = ""
    work_dir: str = ""
    ec2_instance_id: str = ""
    ec2_region: str = ""
    platform: Optional[str] = None
    namespace: Optional[str] = None
    enabled: Optional[bool] = None
    # None means omitted: keep the stored mode. A new row defaults to relay.
    auth_mode: Optional[str] = None


def _node_dict(config: VmConfig) -> dict:
    is_default = config.name == vm_service.DEFAULT_NODE
    return {
        "name": config.name,
        "vm_name": config.vm_name,
        "work_dir": config.work_dir,
        "platform": config.platform,
        "namespace": config.namespace,
        "enabled": config.enabled,
        # NULL is relay. The response always names the mode the next launch uses.
        "auth_mode": config.auth_mode or "relay",
        "is_default": is_default,
        # Generic file/git/terminal execution stays on the default node in v1,
        # so every other row is a chat-only target.
        "chat_only": not is_default,
        "ec2_instance_id": config.ec2_instance_id,
        "ec2_region": config.ec2_region,
        "last_up": config.last_up,
    }


@router.get("/list")
async def list_vm_configs(request: Request):
    user_id = _get_user_id(request)
    return [_node_dict(config) for config in vm_service.list_configs(user_id)]


@router.post("")
async def set_vm_config(req: VmConfigRequest, request: Request):
    user_id = _get_user_id(request)
    name = vm_service.normalize_node_name(req.name)
    config = VmConfig(
        name=name,
        api_token=req.api_token or "",
        vm_name=req.vm_name,
        work_dir=req.work_dir,
        ec2_instance_id=req.ec2_instance_id,
        ec2_region=req.ec2_region,
        platform=req.platform,
        namespace=req.namespace,
        enabled=True if req.enabled is None else req.enabled,
        auth_mode=req.auth_mode,
    )
    if name == vm_service.DEFAULT_NODE:
        # The default node is the orchestrator and is managed by the existing
        # full-config path, never through the node registry editing rules.
        # An omitted auth_mode still preserves the stored value, same as a node.
        existing = vm_service.get_config(user_id, name)
        if req.api_token is None:
            config.api_token = existing.api_token if existing else ""
        try:
            vm_service.assign_auth_mode(config, existing, provided=req.auth_mode is not None)
            vm_service.set_config(user_id, config)
        except vm_service.InvalidNode as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True, "name": name}
    try:
        stored = vm_service.set_node(
            user_id, config,
            api_token_provided=req.api_token is not None,
            enabled_provided=req.enabled is not None,
            auth_mode_provided=req.auth_mode is not None,
        )
    except vm_service.NodeProtected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except vm_service.InvalidNode as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, **_node_dict(stored)}


def _set_enabled(user_id: int, name: str, enabled: bool) -> dict:
    try:
        config = vm_service.set_enabled(user_id, name, enabled)
    except vm_service.NodeProtected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except vm_service.UnknownNode as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "name": config.name, "enabled": config.enabled}


@router.post("/{name}/enable")
async def enable_vm_config(request: Request, name: str):
    return _set_enabled(_get_user_id(request), name, True)


@router.post("/{name}/disable")
async def disable_vm_config(request: Request, name: str):
    return _set_enabled(_get_user_id(request), name, False)


@router.delete("")
async def delete_vm_config(request: Request, name: str = Query("default")):
    user_id = _get_user_id(request)
    try:
        deleted = vm_service.delete_node(user_id, name)
    except vm_service.NodeProtected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except vm_service.NodeInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"unknown node: {vm_service.normalize_node_name(name)}")
    return {"ok": True, "deleted": True}
