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

from loguru import logger

from worker.runner import run_chat, message_callback, check_interrupted
from worker.link_downloader import run_link_download
from worker.process_manager import (
    get_running_processes, try_acquire_lease, renew_lease,
    update_process_offset, complete_process,
)

MAX_PROCESSES_PER_LAMBDA = 100
CONTINUATION_THRESHOLD_MS = 120_000  # 2 min before timeout
IDLE_EXIT_SECONDS = 30
POLL_INTERVAL_SECONDS = 10


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


async def _monitor_loop(deadline_at: float, lambda_req_id: str):
    """Event loop: monitor detached processes, poll for new ones, handle deadlines."""
    from agent.config import resolve_vm_config
    from agent.ssh_pool import SSHPool
    from storage.entity.dto import VmConfig

    ssh_pool = SSHPool()
    tail_tasks = {}  # chat_id -> asyncio.Task
    proc_meta = {}   # chat_id -> proc dict (from DynamoDB)
    idle_since = None

    try:
        while True:
            # 2a. Poll DynamoDB for running processes, acquire new ones
            if len(tail_tasks) < MAX_PROCESSES_PER_LAMBDA:
                procs = get_running_processes()
                for proc in procs:
                    cid = proc["chat_id"]
                    if cid in tail_tasks:
                        continue
                    if len(tail_tasks) >= MAX_PROCESSES_PER_LAMBDA:
                        break
                    if try_acquire_lease(cid, lambda_req_id):
                        proc_meta[cid] = proc
                        task = asyncio.create_task(_tail_and_process(cid, proc, lambda_req_id, deadline_at, ssh_pool))
                        tail_tasks[cid] = task
                        idle_since = None

            # 2b. Reap completed tail tasks
            done = [cid for cid, t in tail_tasks.items() if t.done()]
            for cid in done:
                try:
                    tail_tasks.pop(cid).result()
                except Exception as e:
                    tail_tasks.pop(cid, None)
                    logger.error("tail task {} error: {}", cid, e)
                proc_meta.pop(cid, None)

            # 2c. Idle exit (scale to 0)
            if not tail_tasks:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since > IDLE_EXIT_SECONDS:
                    break
            else:
                idle_since = None

            # 2d. Deadline — let check_deadline_fn trigger natural exit, then cancel stragglers
            if deadline_at and time.monotonic() > deadline_at:
                if tail_tasks:
                    # Wait for tail tasks to finish naturally (check_deadline_fn returns True)
                    done, pending = await asyncio.wait(
                        tail_tasks.values(),
                        timeout=10,
                    )
                    # Force-cancel any that didn't exit in time
                    for task in pending:
                        task.cancel()
                    _send_sqs_continuation()
                break

            # 2e. Renew leases
            for cid in list(tail_tasks.keys()):
                try:
                    renew_lease(cid, lambda_req_id)
                except Exception:
                    pass

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        ssh_pool.close_all()


async def _tail_and_process(chat_id: str, proc: dict, lambda_req_id: str, deadline_at: float, ssh_pool=None):
    """Tail a single detached process and handle completion."""
    from agent.config import resolve_vm_config
    from storage.entity.dto import Message, VmConfig
    from storage.service import chat as chat_service
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    backend_type = proc.get("backend_type", "claude_code")
    vm_name = proc["vm_name"]
    user_id = proc["user_id"]
    offset = proc.get("stdout_offset", 0)
    last_message_id = proc.get("last_message_id")
    session_id = proc.get("session_id")

    vm_config = resolve_vm_config(user_id, vm_name, work_dir=proc.get("work_dir"))

    # Get pooled SSH client if pool is available
    client = ssh_pool.get_or_create(vm_config) if ssh_pool else None

    def _check_deadline():
        if deadline_at and time.monotonic() > deadline_at:
            return True
        return False

    def _check_interrupted():
        return check_interrupted(chat_id)

    def _msg_callback(msg):
        message_callback(chat_id, msg)

    logger.info("tail_and_process start chat_id={} offset={} backend={}", chat_id, offset, backend_type)

    # Dispatch to backend-specific tail function
    if backend_type == "codex":
        from agent.codex import tail_codex_output
        result = await tail_codex_output(
            chat_id=chat_id,
            vm_config=vm_config,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            ssh_client=client,
        )
    else:
        from agent.claude_code import tail_ssh_output
        result = await tail_ssh_output(
            chat_id=chat_id,
            vm_config=vm_config,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            ssh_client=client,
        )

    # Save offset to DynamoDB
    update_process_offset(
        chat_id=chat_id,
        offset=result["offset"],
        last_message_id=result.get("last_message_id"),
        session_id=result.get("session_id") or result.get("thread_id"),
    )

    if result["is_done"]:
        complete_process(chat_id, status=result["status"])

        # Mark chat as no longer running
        from storage.repository import chat as chat_repo
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False

            result_data = result.get("result_data")

            if backend_type == "codex":
                # Codex: usage from turn.completed event
                if result.get("session_id") or result.get("thread_id"):
                    pass  # no external_id for codex
                if result_data and not result_data.get("is_error"):
                    usage = result_data.get("usage", {})
                    if usage:
                        fresh.input_tokens = usage.get("input_tokens")
                        fresh.output_tokens = usage.get("output_tokens")

                if result["status"] == "error":
                    error_text = (result_data.get("result") if result_data else None) or "Codex exited with an error."
                    error_msg = Message(
                        id=generate_message_id(),
                        role="assistant",
                        content=error_text,
                        timestamp=get_utc_iso8601_timestamp(),
                        unix_timestamp=get_unix_timestamp(),
                    )
                    _msg_callback(error_msg)
            else:
                # Claude Code: existing logic
                if result.get("session_id"):
                    fresh.external_id = result["session_id"]

                if result_data:
                    model_usage = result_data.get("modelUsage", {})
                    num_turns = result_data.get("num_turns") or 1
                    if model_usage:
                        fresh.input_tokens = sum(v.get("inputTokens", 0) for v in model_usage.values()) // num_turns
                        fresh.output_tokens = sum(v.get("outputTokens", 0) for v in model_usage.values()) // num_turns
                        fresh.cache_read_input_tokens = sum(v.get("cacheReadInputTokens", 0) for v in model_usage.values()) // num_turns
                        fresh.cache_creation_input_tokens = sum(v.get("cacheCreationInputTokens", 0) for v in model_usage.values()) // num_turns
                        fresh.context_window = max((v.get("contextWindow", 0) for v in model_usage.values()), default=None)

                    if result["status"] == "error":
                        error_text = result_data.get("result") or "Claude Code exited with an error."
                        error_msg = Message(
                            id=generate_message_id(),
                            role="assistant",
                            content=error_text,
                            timestamp=get_utc_iso8601_timestamp(),
                            unix_timestamp=get_unix_timestamp(),
                        )
                        _msg_callback(error_msg)

            await chat_repo.save_chat_by_id(fresh)

            # Telegram reply + post hooks (same for both backends)
            if not fresh.interrupted and result["status"] != "error":
                try:
                    from worker.runner import _send_telegram_reply
                    _send_telegram_reply(fresh, user_id, proc.get("trace_id"))
                except Exception as e:
                    logger.exception("telegram reply failed: {}", e)

                post_hooks = proc.get("post_hooks")
                if post_hooks:
                    if isinstance(post_hooks, str):
                        post_hooks = json.loads(post_hooks)
                    from worker.runner import _run_post_hooks
                    _run_post_hooks(fresh, user_id, post_hooks, trace_id=proc.get("trace_id"))

        logger.info("tail_and_process done chat_id={} status={}", chat_id, result["status"])
    else:
        logger.info("tail_and_process paused chat_id={} offset={}", chat_id, result["offset"])


def _send_sqs_continuation():
    """Send a continuation message to SQS to trigger a new Lambda for remaining processes."""
    import boto3
    queue_url = os.environ.get("SQS_QUEUE_URL")
    if not queue_url:
        return
    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"task_type": "continuation"}),
    )
    logger.info("Sent SQS continuation message")
