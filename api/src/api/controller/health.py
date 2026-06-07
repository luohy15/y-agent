from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health():
    """Static liveness ping. No DB, no auth — used by the web app to warm the
    Lambda on open (whitelisted in AuthMiddleware)."""
    return {"status": "ok"}
