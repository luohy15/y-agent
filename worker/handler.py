"""Worker Lambda handler — triggered by SQS to run chats.

Two-phase architecture:
  Phase 1: Process SQS records (start detached processes or run inline)
  Phase 2: Event loop monitoring detached processes via tail + DynamoDB
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from worker.runner import run_chat
from worker.link_downloader import run_link_download
from worker.process_manager import get_running_processes
from worker.monitor import _monitor_loop

CONTINUATION_THRESHOLD_MS = 120_000  # 2 min before timeout


async def _process_record(body: dict) -> str:
    """Process a single SQS record body.

    Returns 'done', 'detached', or 'continuation'.
    """
    task_type = body.get("task_type", "chat")

    if task_type == "link_download":
        print(f"[worker] SQS trigger for link_download link_id={body['link_id']} url={body['url']}")
        await run_link_download(
            user_id=body["user_id"],
            link_id=body["link_id"],
            url=body["url"],
            activity_id=body.get("activity_id"),
        )
        return "done"

    if task_type == "continuation":
        return "continuation"

    # All chat tasks go through run_chat (detached vs inline decided internally)
    chat_id = body["chat_id"]
    print(f"[worker] SQS trigger for chat {chat_id}")
    result = await run_chat(
        user_id=body.get("user_id"),
        chat_id=chat_id,
        bot_name=body.get("bot_name"),
        vm_name=body.get("vm_name"),
        work_dir=body.get("work_dir"),
        post_hooks=body.get("post_hooks"),
        trace_id=body.get("trace_id"),
        skill=body.get("skill"),
        backend=body.get("backend"),
    )
    return result


def lambda_handler(event, context):
    """Handle SQS trigger with two-phase processing."""
    records = event.get("Records", [])

    async def main():
        # Compute deadline
        deadline_at = None
        if context and hasattr(context, "get_remaining_time_in_millis"):
            remaining_ms = context.get_remaining_time_in_millis()
            deadline_at = time.monotonic() + (remaining_ms - CONTINUATION_THRESHOLD_MS) / 1000
        lambda_req_id = context.aws_request_id if context and hasattr(context, "aws_request_id") else "local"

        # === Phase 1: Process SQS records concurrently ===
        tasks = []
        for record in records:
            body = json.loads(record["body"])
            tasks.append(_process_record(body))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect failures and check for detached processes
        failures = []
        has_detached = False
        for record, result in zip(records, results):
            if isinstance(result, Exception):
                message_id = record["messageId"]
                print(f"[worker] Record {message_id} failed in phase 1: {result}")
                failures.append({"itemIdentifier": message_id})
            elif result in ("continuation", "detached"):
                has_detached = True

        # === Phase 2: Event loop (only when there are detached processes) ===
        if not has_detached and not get_running_processes():
            if failures:
                return {"batchItemFailures": failures}
            return {"status": "ok", "processed": len(records)}

        await _monitor_loop(deadline_at, lambda_req_id)

        if failures:
            return {"batchItemFailures": failures}
        return {"status": "ok"}

    result = asyncio.run(main())
    return result
