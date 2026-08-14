"""Scheduled action: pull LLM token/cost usage into model_usage_daily + hourly.

Runs hourly on an EventBridge cron (minute 50). CRS usage is per-user (each
user's sync enumerates all distinct cr_ relay keys in their bot_configs and
sums per model into the global per-model aggregate), so it iterates users.

Daily upserts key on (user, date, source, scope_id, model); hourly adds
usage_hour. Re-pulling the in-progress day/hour overwrites; finalized past
rows are no-ops. Hourly covers [yesterday, today] so the previous day's final
hour is repaired after midnight (todo 3165).
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
            # Full sync envelope: daily + hourly (crs-hourly) results.
            results.append(usage_service.sync(user.id))

        total_rows = 0
        for envelope in results:
            for r in envelope.get("results") or []:
                total_rows += r.get("rows", 0)
        logger.info("sync_model_usage: {} pulls, {} rows total", len(results), total_rows)
        return {"status": "ok", "action": LOCK_NAME, "rows": total_rows, "results": results}
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
