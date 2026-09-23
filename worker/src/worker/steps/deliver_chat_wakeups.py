"""Outbox delivery for registered scheduled chat wakeups (todo 3655).

A wakeup is created in its own transaction (API); this scheduled pass is what
makes delivery durable rather than best-effort -- a crash between accept and
enqueue leaves a receipt behind, and this retries it. Server-side delivery,
not session polling: a waiting session never checks anything. Delivery is
at-least-once -- a crash after the broker send can repeat it -- which is safe
because the append is deduplicated by event id (the wakeup_id) and the worker
already excludes a second run of one chat.

Runs every minute (its own schedule): the 5-minute watchdog tick would give 5
to 10 minutes of jitter, too coarse for a timer a session is waiting on.
"""

from loguru import logger

from storage.repository import user as user_repo
from storage.service import chat_wakeup as wakeup_service
from storage.service import pipeline_lock as pipeline_lock_service

LOCK_NAME = "deliver_chat_wakeups"
BATCH_SIZE = 100


async def run_pass() -> dict:
    states = {}
    for wakeup in wakeup_service.due_wakeups(BATCH_SIZE):
        user = user_repo.get_user_by_user_id(wakeup.user_id)
        if user is None:
            logger.warning("[chat-wakeup] skipping wakeup for unknown account wakeup={}",
                           wakeup.wakeup_id)
            continue
        state = await wakeup_service.deliver_wakeup(wakeup, user.id)
        states[state] = states.get(state, 0) + 1
    return {"status": "ok", "action": LOCK_NAME, "delivered": states}


async def handle_deliver_chat_wakeups() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("deliver_chat_wakeups: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}
    try:
        result = await run_pass()
        if result["status"] == "ok":
            pipeline_lock_service.record_success(LOCK_NAME)
        logger.info("deliver_chat_wakeups: {}", result)
        return result
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
