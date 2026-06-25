"""Scheduled action: pull daily LLM token/cost usage into model_usage_daily.

Runs daily on an EventBridge cron. CRS usage is per-user (each user's sync
enumerates all distinct cr_ relay keys in their bot_configs and sums per model
into the global per-model aggregate), so it iterates users.

The pull is an idempotent upsert keyed on (user, date, source, scope_id, model),
which matches CRS's ~30-day retention window: re-pulling the in-progress day
overwrites, a finalized past day is a no-op.
"""

from loguru import logger

from storage.service import model_usage_daily as usage_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service.user import list_users


LOCK_NAME = "sync_model_usage"


async def handle_sync_model_usage() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("sync_model_usage: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        results = []
        for user in list_users():
            results.append(usage_service.sync_crs(user.id))

        total_rows = sum(r.get("rows", 0) for r in results)
        logger.info("sync_model_usage: {} pulls, {} rows total", len(results), total_rows)
        return {"status": "ok", "action": LOCK_NAME, "rows": total_rows, "results": results}
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
