"""Worker Lambda handler — dual-route for SQS records and scheduled events.

- SQS records: two-phase (detached processes + monitor loop) for chats, inline
  for `trigger_batch_download` nudges.
- Scheduled events (no `Records`, has `action`): route by action to the
  corresponding step handler (`fetch_rss_links` / `batch_download_links`).
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from loguru import logger

from worker.runner import run_chat
from worker.process_manager import get_running_processes
from worker.monitor import _monitor_loop

CONTINUATION_THRESHOLD_MS = 120_000  # 2 min before timeout


def _handle_scheduled_action(action: str, event: dict) -> dict:
    if action == "fetch_rss_links":
        from worker.steps.fetch_rss_links import handle_fetch_rss_links
        return asyncio.run(handle_fetch_rss_links())
    if action == "scrape_rss_sources":
        from worker.steps.scrape_rss_sources import handle_scrape_rss_sources
        return asyncio.run(handle_scrape_rss_sources())
    if action == "batch_download_links":
        from worker.steps.batch_download_links import handle_batch_download_links
        return asyncio.run(handle_batch_download_links())
    return {"status": "error", "message": f"Unknown action: {action}"}


async def _process_record(body: dict) -> str:
    """Process a single SQS record body.

    Returns 'done', 'detached', or 'continuation'.
    """
    task_type = body.get("task_type", "chat")

    if task_type == "trigger_batch_download":
        logger.info("[worker] SQS trigger for batch_download_links")
        from worker.steps.batch_download_links import handle_batch_download_links
        await handle_batch_download_links()
        return "done"

    if task_type == "continuation":
        return "continuation"

    # All chat tasks go through run_chat (detached vs inline decided internally)
    chat_id = body["chat_id"]
    logger.info("[worker] SQS trigger for chat {}", chat_id)
    result = await run_chat(
        user_id=body.get("user_id"),
        chat_id=chat_id,
        bot_name=body.get("bot_name"),
        vm_name=body.get("vm_name"),
        work_dir=body.get("work_dir"),
        post_hooks=body.get("post_hooks"),
        trace_id=body.get("trace_id"),
        role=body.get("role"),
        topic=body.get("topic"),
        backend=body.get("backend"),
    )
    return result


def lambda_handler(event, context):
    """Handle SQS trigger with two-phase processing, or route scheduled actions."""
    # Scheduled event: no SQS records, carries an action field
    if "Records" not in event and "action" in event:
        action = event["action"]
        logger.info("[worker] scheduled action={} event={}", action, json.dumps(event))
        return _handle_scheduled_action(action, event)

    records = event.get("Records", [])

    async def main():
        # Compute deadline
        deadline_at = None
        if context and hasattr(context, "get_remaining_time_in_millis"):
            remaining_ms = context.get_remaining_time_in_millis()
            deadline_at = time.monotonic() + (remaining_ms - CONTINUATION_THRESHOLD_MS) / 1000
        lambda_req_id = context.aws_request_id if context and hasattr(context, "aws_request_id") else "local"

        # === Phase 1: Process the single SQS record (BatchSize=1) ===
        body = json.loads(records[0]["body"])
        result = await _process_record(body)

        # === Phase 2: Event loop (only when there are detached processes) ===
        if result not in ("continuation", "detached") and not get_running_processes():
            return {"status": "ok"}

        await _monitor_loop(deadline_at, lambda_req_id)
        return {"status": "ok"}

    result = asyncio.run(main())
    return result
