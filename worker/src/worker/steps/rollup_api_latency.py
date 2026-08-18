"""Scheduled API latency rollup and retention maintenance."""

from loguru import logger

from storage.service import api_latency as latency_service
from storage.service import pipeline_lock as pipeline_lock_service


LOCK_NAME = "rollup_api_latency"


async def handle_rollup_api_latency() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("rollup_api_latency: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        result = latency_service.run_maintenance()
        logger.info(
            "rollup_api_latency: hourly={} daily={} hot_hours={} dirty_hours={} repaired_hours={} deleted={}",
            result["hourly_rows"],
            result["daily_rows"],
            result["hot_hours"],
            result["dirty_hours"],
            result["repaired_hours"],
            result["deleted"],
        )
        return {"status": "ok", "action": LOCK_NAME, **result}
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
