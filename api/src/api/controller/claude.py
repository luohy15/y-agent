"""Read-only Claude limit-window usage endpoint.

Pure DB read of the cached `/usage` scrape (`vm_config.claude_usage`), warmed
out-of-band by the `y claude usage` write-through. Never triggers a live scrape.
"""

from fastapi import APIRouter, Query, Request

from storage.service import vm_config as vm_service

router = APIRouter(prefix="/claude")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/usage")
async def get_claude_usage(request: Request, vm_name: str | None = Query(None)):
    user_id = _get_user_id(request)
    name = vm_name or "default"
    blob = vm_service.get_claude_usage(user_id, name)
    if not blob:
        return {"cached": False}
    return blob
