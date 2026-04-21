"""Event loop that monitors detached tmux chat processes.

Shared by Lambda handler (with deadline_at from Lambda context) and Celery
worker (with deadline_at=None for local dev).
"""

import asyncio
import json
import os
import time

from loguru import logger

from worker.process_manager import (
    get_running_processes, try_acquire_lease, renew_lease,
    update_process_offset, complete_process, release_lease,
)
from worker.runner import message_callback, check_interrupted

MAX_PROCESSES_PER_LAMBDA = 100
IDLE_EXIT_SECONDS = 30
POLL_INTERVAL_SECONDS = 10
MAX_TAIL_RETRIES = 3
HARD_TIMEOUT_SECONDS = 3600  # 1 hour


class TailRetryableError(Exception):
    """Raised when tail exits with error but is_done=False, signaling a retryable failure."""
    pass


async def _monitor_loop(deadline_at: float, lambda_req_id: str):
    """Event loop: monitor detached processes, poll for new ones, handle deadlines."""
    from agent.ssh_pool import SSHPool

    ssh_pool = SSHPool()
    tail_tasks = {}  # chat_id -> asyncio.Task
    proc_meta = {}   # chat_id -> proc dict (from DynamoDB)
    error_counts = {}  # chat_id -> consecutive error count
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
                        # Hard timeout check: if process has been running too long, stop it
                        started_at = proc.get("started_at", 0)
                        if started_at and time.time() - started_at > HARD_TIMEOUT_SECONDS:
                            logger.warning("hard timeout: chat_id={} started_at={} elapsed={}s", cid, started_at, int(time.time() - started_at))
                            await _handle_timeout(cid, proc, ssh_pool)
                            continue

                        proc_meta[cid] = proc
                        task = asyncio.create_task(_tail_and_process(cid, proc, lambda_req_id, deadline_at, ssh_pool))
                        tail_tasks[cid] = task
                        idle_since = None

            # 2b. Reap completed tail tasks
            done = [cid for cid, t in tail_tasks.items() if t.done()]
            for cid in done:
                try:
                    tail_tasks.pop(cid).result()
                    error_counts.pop(cid, None)  # success or normal pause → reset
                except TailRetryableError as e:
                    tail_tasks.pop(cid, None)
                    error_counts[cid] = error_counts.get(cid, 0) + 1
                    if error_counts[cid] >= MAX_TAIL_RETRIES:
                        logger.error("tail task {} exceeded max retries ({}), marking as error", cid, MAX_TAIL_RETRIES)
                        complete_process(cid, status="error")
                        await _mark_chat_stopped(cid)
                        error_counts.pop(cid, None)
                    else:
                        logger.warning("tail task {} retryable error (attempt {}/{}): {}", cid, error_counts[cid], MAX_TAIL_RETRIES, e)
                except Exception as e:
                    tail_tasks.pop(cid, None)
                    error_counts[cid] = error_counts.get(cid, 0) + 1
                    if error_counts[cid] >= MAX_TAIL_RETRIES:
                        logger.error("tail task {} exceeded max retries ({}), marking as error: {}", cid, MAX_TAIL_RETRIES, e)
                        complete_process(cid, status="error")
                        await _mark_chat_stopped(cid)
                        error_counts.pop(cid, None)
                    else:
                        logger.warning("tail task {} error (attempt {}/{}): {}", cid, error_counts[cid], MAX_TAIL_RETRIES, e)
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
                    task_to_cid = {t: cid for cid, t in tail_tasks.items()}
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.wait(pending, timeout=5)
                    # Release leases for cancelled tasks so continuation Lambda can acquire them
                    for task in pending:
                        cid = task_to_cid.get(task)
                        if cid:
                            try:
                                release_lease(cid)
                            except Exception:
                                pass
                # Always check for running processes — tail_tasks may already be reaped
                if get_running_processes():
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
    from storage.entity.dto import Message
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

    started_at = proc.get("started_at", 0)

    def _check_deadline():
        if deadline_at and time.monotonic() > deadline_at:
            return True
        # Secondary hard timeout check during tail
        if started_at and time.time() - started_at > HARD_TIMEOUT_SECONDS:
            return True
        return False

    def _check_interrupted():
        return check_interrupted(chat_id)

    def _msg_callback(msg):
        message_callback(chat_id, msg)

    # Build steer checker for detached claude_code processes
    steer_fn = None
    if backend_type != "codex":
        chat = await chat_service.get_chat_by_id(chat_id)
        initial_msg_count = proc.get("initial_msg_count", len(chat.messages) if chat else 0)
        initial_msg_ids = {msg.id for msg in (chat.messages[:initial_msg_count] if chat else []) if msg.id}
        # Load previously consumed steer IDs from prior Lambda
        prev_consumed = set()
        raw_consumed = proc.get("consumed_steer_ids")
        if raw_consumed:
            try:
                prev_consumed = set(json.loads(raw_consumed) if isinstance(raw_consumed, str) else raw_consumed)
            except (json.JSONDecodeError, TypeError):
                pass
        from worker.runner import make_steer_checker
        steer_fn = make_steer_checker(chat_id, initial_msg_ids, previously_consumed=prev_consumed)

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
            check_steer_fn=steer_fn,
        )

    # Save offset to DynamoDB
    update_process_offset(
        chat_id=chat_id,
        offset=result["offset"],
        last_message_id=result.get("last_message_id"),
        session_id=result.get("session_id") or result.get("thread_id"),
        consumed_steer_ids=result.get("consumed_steer_ids"),
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

            # Mark as unread on successful completion
            if not fresh.interrupted and result["status"] != "error":
                from storage.repository.chat import set_chat_unread
                set_chat_unread(chat_id, True)

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
        # Check if paused due to hard timeout (not just Lambda deadline)
        if started_at and time.time() - started_at > HARD_TIMEOUT_SECONDS:
            logger.warning("hard timeout (mid-tail): chat_id={} started_at={} elapsed={}s", chat_id, started_at, int(time.time() - started_at))
            await _handle_timeout(chat_id, proc, ssh_pool)
            return

        release_lease(chat_id)
        if result.get("status") == "error":
            logger.info("tail_and_process error (retryable) chat_id={} offset={}", chat_id, result["offset"])
            raise TailRetryableError(f"tail error for {chat_id}, offset={result['offset']}")
        logger.info("tail_and_process paused chat_id={} offset={}", chat_id, result["offset"])


async def _handle_timeout(chat_id: str, proc: dict, ssh_pool=None):
    """Handle hard timeout: kill tmux, complete process, mark chat stopped, add message, notify."""
    from agent.config import resolve_vm_config
    from storage.entity.dto import Message
    from storage.service import chat as chat_service
    from storage.repository import chat as chat_repo
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    # 1. Kill tmux session on remote
    user_id = proc["user_id"]
    vm_name = proc["vm_name"]
    try:
        vm_config = resolve_vm_config(user_id, vm_name, work_dir=proc.get("work_dir"))
        client = ssh_pool.get_or_create(vm_config) if ssh_pool else None
        if client:
            client.exec_command(
                f"tmux kill-session -t 'cc-{chat_id}' 2>/dev/null; "
                f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.stdout /tmp/cc-{chat_id}.stderr /tmp/cc-{chat_id}.exit 2>/dev/null"
            )
            logger.info("hard timeout: killed tmux session for chat_id={}", chat_id)
    except Exception as e:
        logger.exception("hard timeout: failed to kill tmux for chat_id={}: {}", chat_id, e)

    # 2. Mark process as timed out in DynamoDB
    complete_process(chat_id, status="timeout")

    # 3. Mark chat as stopped + add timeout message
    fresh = await chat_service.get_chat_by_id(chat_id)
    if fresh:
        fresh.running = False

        elapsed = int(time.time() - proc.get("started_at", 0))
        timeout_text = f"This chat was automatically stopped after running for {elapsed // 60} minutes (hard timeout: {HARD_TIMEOUT_SECONDS // 60} min)."
        timeout_msg = Message(
            id=generate_message_id(),
            role="assistant",
            content=timeout_text,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        message_callback(chat_id, timeout_msg)

        await chat_repo.save_chat_by_id(fresh)

        # 4. Send Telegram notification
        try:
            from worker.runner import _resolve_telegram_target
            from storage.util import send_telegram_message
            target = _resolve_telegram_target(fresh, user_id)
            if target:
                bot_token, tg_chat_id, topic_id = target
                send_telegram_message(bot_token, tg_chat_id, f"⏰ {timeout_text}", topic_id)
                logger.info("hard timeout: telegram notification sent for chat_id={}", chat_id)
        except Exception as e:
            logger.exception("hard timeout: telegram notification failed for chat_id={}: {}", chat_id, e)

    logger.info("hard timeout: completed handling for chat_id={}", chat_id)


async def _mark_chat_stopped(chat_id: str):
    """Mark a chat as not running after max retries exceeded."""
    from storage.service import chat as chat_service
    from storage.repository import chat as chat_repo
    fresh = await chat_service.get_chat_by_id(chat_id)
    if fresh:
        fresh.running = False
        await chat_repo.save_chat_by_id(fresh)


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
