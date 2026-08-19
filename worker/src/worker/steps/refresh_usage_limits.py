"""Scheduled action: refresh each user's persisted subscription limit-window
snapshot (`user_preference` key `usage_limits_latest`) so ordinary
`GET /api/usage/limits` reads never touch the VM/SSH/CLI path (todo 3226).

Runs the same `agent.usage_limits.refresh_and_persist_snapshot` the explicit
`?refresh=true` API path uses, one user at a time. Each call acquires that
user's own `refresh_usage_limits:<user_id>` pipeline lock internally, so a
user whose previous sweep (or a concurrent manual refresh) is still running
is simply skipped for this tick rather than doubled up; one user's failure
does not block the rest.
"""

from loguru import logger

from agent.usage_limits import refresh_and_persist_snapshot
from storage.service.user import list_users


async def handle_refresh_usage_limits() -> dict:
    results = []
    for user in list_users():
        try:
            snapshot = await refresh_and_persist_snapshot(user.id, force=False)
        except Exception:
            logger.exception("refresh_usage_limits: unhandled error for user_id={}", user.id)
            results.append({"user_id": user.id, "status": "error"})
            continue
        if snapshot is None:
            results.append({"user_id": user.id, "status": "skip"})
            continue
        results.append({"user_id": user.id, "status": snapshot.get("last_attempt_status")})

    ok = sum(1 for r in results if r.get("status") == "ok")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skip")
    logger.info(
        "refresh_usage_limits: {} users, {} ok, {} failed, {} skipped",
        len(results), ok, failed, skipped,
    )
    return {
        "status": "ok",
        "action": "refresh_usage_limits",
        "users": len(results),
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
    }
