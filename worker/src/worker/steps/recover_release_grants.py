"""Outbox recovery for publication-grant wakeups (todo 3493).

A grant writes its wakeup event in the same transaction as ownership, and the
API attempts delivery right after that commit. This scheduled pass is what
makes the wakeup durable rather than best-effort: a lost HTTP response, an API
crash or a broker error leaves a receipt behind, and this retries it.

Server-side recovery, not session polling: a waiting coordinator never checks
anything. Delivery is at-least-once -- a crash after the broker send can repeat
it -- which is safe because the append is deduplicated by event id and the
worker already excludes a second run of one chat.
"""

from loguru import logger

from storage.repository import user as user_repo
from storage.repository import dev_release as release_repo
from storage.service import dev_release as release_service

BATCH_SIZE = 50


async def handle_recover_release_grants():
    states = {}
    for waiter in release_repo.pending_wakeups(BATCH_SIZE):
        user = user_repo.get_user_by_user_id(waiter.user_id)
        if user is None:
            logger.warning("[dev-release] skipping wakeup for unknown account waiter={}",
                           waiter.waiter_id)
            continue
        state = await release_service.deliver_grant(waiter, user.id)
        states[state] = states.get(state, 0) + 1
    return {"status": "ok", "delivered": states}
