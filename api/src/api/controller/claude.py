"""Claude limit-window usage endpoints.

GET is a pure DB read of the cached `/usage` scrape (`vm_config.claude_usage`),
warmed out-of-band by the `y claude usage` write-through or by the POST refresh
below. It is the mount-time read and never triggers a live scrape.

POST /usage/refresh applies the cache TTL rule: if the cached blob is at most
`CLAUDE_USAGE_TTL_SECONDS` old it is returned as-is; otherwise this request
synchronously runs the Claude `/usage` TUI scrape, drops the heavy raw pane,
stamps `scraped_at`, persists, and returns the fresh blob.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from agent import config as agent_config
from agent.claude_usage import read_claude_usage
from storage.service import vm_config as vm_service

router = APIRouter(prefix="/claude")

CLAUDE_USAGE_TTL_SECONDS = 600


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _scraped_at_age_seconds(blob: dict) -> float | None:
    raw = blob.get("scraped_at")
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


@router.get("/usage")
async def get_claude_usage(request: Request, vm_name: str | None = Query(None)):
    user_id = _get_user_id(request)
    name = vm_name or "default"
    blob = vm_service.get_claude_usage(user_id, name)
    if not blob:
        return {"cached": False}
    return blob


@router.post("/usage/refresh")
async def refresh_claude_usage(request: Request, vm_name: str | None = Query(None)):
    user_id = _get_user_id(request)
    name = vm_name or "default"

    blob = vm_service.get_claude_usage(user_id, name)
    if blob:
        age = _scraped_at_age_seconds(blob)
        if age is not None and age <= CLAUDE_USAGE_TTL_SECONDS:
            return blob

    vm_config = agent_config.resolve_vm_config(user_id, name)
    result = await read_claude_usage(vm_config)

    envelope = {
        "data": {
            "session": result.get("session"),
            "week_all": result.get("week_all"),
            "week_sonnet": result.get("week_sonnet"),
        },
        "parse_ok": result.get("parse_ok", False),
        "source": "claude_tui",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        vm_service.save_claude_usage(user_id, vm_config.name, envelope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to cache usage: {exc}") from exc
    return envelope
