from fastapi import APIRouter, Query, Request

from storage.service import bot_config as bot_service

router = APIRouter(prefix="/bot")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/config")
async def get_bot_config(request: Request, name: str = Query("default")):
    user_id = _get_user_id(request)
    config = bot_service.get_config(user_id, name)
    if config is None:
        return {"name": name}
    return {
        "name": config.name,
        "model": config.model,
        "description": config.description,
    }
