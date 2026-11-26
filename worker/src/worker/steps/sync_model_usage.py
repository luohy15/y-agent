"""Scheduled action: pull LLM token/cost usage into model_usage_daily + hourly.

Runs every 5 minutes on an EventBridge schedule (todo 4465; hourly at minute 50
before that). CRS usage is per-user (each
user's sync enumerates all distinct cr_ relay keys in their bot_configs and
sums per model into the global per-model aggregate), so it iterates users.

Daily upserts key on (user, date, source, scope_id, model); hourly adds
usage_hour. Re-pulling the in-progress day/hour overwrites; finalized past
rows are no-ops. Hourly covers [yesterday, today] so the previous day's final
hour is repaired after midnight (todo 3165).
"""

from datetime import timedelta

from loguru import logger

from storage.service import chat_model_activity as activity_service
from storage.service import model_usage_daily as usage_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service.user import list_users
from storage.util import local_today


LOCK_NAME = "sync_model_usage"
MISMATCH_LIMIT = 20


def _counter_mismatches(user_id: int) -> list[dict]:
    """Daily (date, model) cells where answered turns exceed recorded requests.

    Turns are attributed answered prompt groups; an agy Request is one of the
    attributed assistant messages the fold saw, so every Turn coincides with a
    Request and turns > requests means the aggregates are stale or a relay turn
    lost its usage row (todo 4483). Only cells carrying a usage row are
    compared: activity-only models (inline search) have no request count to
    compare against. The two-day window matches the agy recompute range.
    """
    today = local_today()
    mismatches = []
    for offset in (0, 1):
        day = today - timedelta(days=offset)
        day_str = day.isoformat()
        turns = {
            row["model"]: row["turns"]
            for row in activity_service.aggregate(user_id, day, day)["models"]
        }
        requests: dict[str, int] = {}
        for row in usage_service.list_for(user_id, from_date=day_str, to_date=day_str):
            requests[row.model] = requests.get(row.model, 0) + (row.requests or 0)
        for model, turn_count in turns.items():
            request_count = requests.get(model)
            if request_count is not None and turn_count > request_count:
                mismatches.append({
                    "usage_date": day_str,
                    "model": model,
                    "turns": turn_count,
                    "requests": request_count,
                })
    return mismatches


async def handle_sync_model_usage() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("sync_model_usage: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        results = []
        mismatches = []
        for user in list_users():
            # Activity first: the agy aggregate reads its request counts, so a
            # fresh turn must be folded before the usage pull (todo 4483).
            try:
                activity = activity_service.sync(user.id)
                activity_ok = True
            except Exception as exc:
                logger.opt(exception=exc).error(
                    "sync_model_usage: chat activity sync failed for user {}: {}",
                    user.id,
                    exc,
                )
                activity = {"status": "error", "rows": 0}
                activity_ok = False
            # Full relay sync envelope: daily + hourly (crs-hourly) results.
            envelope = usage_service.sync(user.id, activity_synced=activity_ok)
            envelope["activity"] = activity
            try:
                user_mismatches = _counter_mismatches(user.id)
            except Exception as exc:
                logger.warning(
                    "sync_model_usage: counter check failed for user {}: {}",
                    user.id,
                    type(exc).__name__,
                )
                user_mismatches = []
            if user_mismatches:
                logger.warning(
                    "sync_model_usage: turns exceed requests for user {}: {} cell(s), sample={}",
                    user.id,
                    len(user_mismatches),
                    user_mismatches[:3],
                )
            mismatches.extend(user_mismatches)
            results.append(envelope)

        total_rows = 0
        for envelope in results:
            for r in envelope.get("results") or []:
                total_rows += r.get("rows", 0)
        logger.info("sync_model_usage: {} pulls, {} rows total", len(results), total_rows)
        return {
            "status": "ok",
            "action": LOCK_NAME,
            "rows": total_rows,
            "results": results,
            "counter_mismatches": mismatches[:MISMATCH_LIMIT],
        }
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
