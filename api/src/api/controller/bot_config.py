from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.entity.dto import BotConfig
from storage.service import bot_config as bot_service

router = APIRouter(prefix="/bot")


class BotConfigRequest(BaseModel):
    name: str
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: Optional[str] = None
    backend: Optional[str] = None
    model: str = ""
    description: Optional[str] = None
    max_tokens: Optional[int] = None
    custom_api_path: Optional[str] = None


class UpdateBotConfigRequest(BaseModel):
    name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    backend: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    max_tokens: Optional[int] = None
    custom_api_path: Optional[str] = None


class BotNameRequest(BaseModel):
    name: str


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def list_bot_configs(request: Request):
    user_id = _get_user_id(request)
    configs = bot_service.list_configs(user_id)
    return [
        {
            "name": c.name,
            "backend": c.backend or c.api_type,
            "model": c.model,
            "description": c.description,
            "has_api_key": bool(c.api_key),
        }
        for c in configs
    ]


@router.get("/config")
async def get_bot_config(request: Request, name: str = Query("default")):
    user_id = _get_user_id(request)
    config = bot_service.get_config(user_id, name)
    if config is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {
        "name": config.name,
        "base_url": config.base_url,
        "backend": config.backend or config.api_type,
        "model": config.model,
        "description": config.description,
        "max_tokens": config.max_tokens,
        "custom_api_path": config.custom_api_path,
        "has_api_key": bool(config.api_key),
    }


@router.post("")
async def create_bot_config(request: Request, req: BotConfigRequest):
    user_id = _get_user_id(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    config = BotConfig(
        name=name,
        base_url=req.base_url.strip() or "https://openrouter.ai/api/v1",
        api_key=req.api_key or "",
        backend=req.backend or None,
        model=req.model.strip(),
        description=req.description or None,
        max_tokens=req.max_tokens,
        custom_api_path=req.custom_api_path or None,
    )
    bot_service.add_config(user_id, config)
    return {"ok": True, "name": name}


@router.post("/update")
async def update_bot_config(request: Request, req: UpdateBotConfigRequest):
    user_id = _get_user_id(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    existing = bot_service.get_config(user_id, name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    fields_set = getattr(req, "model_fields_set", getattr(req, "__fields_set__", set()))
    config = BotConfig(
        name=name,
        base_url=(
            req.base_url.strip() if "base_url" in fields_set and req.base_url and req.base_url.strip()
            else existing.base_url
        ),
        api_key=existing.api_key if "api_key" not in fields_set else (req.api_key or ""),
        backend=existing.backend if "backend" not in fields_set else (req.backend or None),
        model=existing.model if "model" not in fields_set else (req.model or "").strip(),
        description=existing.description if "description" not in fields_set else (req.description or None),
        openrouter_config=existing.openrouter_config,
        prompts=existing.prompts,
        max_tokens=existing.max_tokens if "max_tokens" not in fields_set else req.max_tokens,
        custom_api_path=(
            existing.custom_api_path if "custom_api_path" not in fields_set else (req.custom_api_path or None)
        ),
    )
    bot_service.add_config(user_id, config)
    return {"ok": True, "name": name}


@router.post("/delete")
async def delete_bot_config(request: Request, req: BotNameRequest):
    user_id = _get_user_id(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if name == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default bot configuration")
    if not bot_service.delete_config(user_id, name):
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"ok": True, "name": name}
