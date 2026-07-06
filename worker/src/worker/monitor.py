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
ORPHAN_RUNNING_CHAT_GRACE_SECONDS = 15 * 60


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
        await _sweep_orphan_running_chats()

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

    # Build steer checker. claude_code injects steer into the live stdin pipe;
    # codex/gemini_cli can't take a live steer, so their tailers return
    # status="steer" and the run is restarted via the backend resume command.
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
            check_steer_fn=steer_fn,
            ssh_client=client,
        )
    elif backend_type == "gemini_cli":
        from agent.gemini_cli import tail_gemini_output
        result = await tail_gemini_output(
            chat_id=chat_id,
            vm_config=vm_config,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
            ssh_client=client,
        )
    elif backend_type == "pi_cli":
        from agent.pi_cli import tail_pi_output
        result = await tail_pi_output(
            chat_id=chat_id,
            vm_config=vm_config,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
            ssh_client=client,
        )
    elif backend_type == "claude_tui":
        from agent.claude_tui import tail_claude_tui_output
        result = await tail_claude_tui_output(
            chat_id=chat_id,
            vm_config=vm_config,
            work_dir=proc.get("work_dir"),
            session_id=session_id,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
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

    # Non-live steer: the run was killed mid-flight; restart with the steer
    # text as the new prompt.
    if result.get("status") == "steer":
        if backend_type == "gemini_cli":
            await _restart_gemini_with_steer(chat_id, proc, result)
        elif backend_type == "pi_cli":
            await _restart_pi_with_steer(chat_id, proc, result)
        else:
            await _restart_codex_with_steer(chat_id, proc, result)
        return

    # Save offset to DynamoDB
    # Defensive: keep prior session_id when this tail did not observe a fresh one.
    updated_session_id = result.get("session_id") or result.get("thread_id") or session_id
    # Merge with prior-Lambda-handoff consumed ids (matches the restart-with-steer
    # paths above) — update_process_offset overwrites rather than merges, so a
    # plain completion that skips this would forget ids confirmed in an earlier
    # handoff and risk re-delivering them on a later one.
    all_consumed_steer_ids = list(prev_consumed) + list(result.get("consumed_steer_ids") or [])
    update_process_offset(
        chat_id=chat_id,
        offset=result["offset"],
        last_message_id=result.get("last_message_id"),
        session_id=updated_session_id,
        consumed_steer_ids=all_consumed_steer_ids,
    )

    if result["is_done"]:
        # Mark chat as no longer running
        from storage.repository import chat as chat_repo
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)

            try:
                await _apply_completion_metadata(
                    fresh=fresh,
                    result=result,
                    result_data=result.get("result_data"),
                    proc=proc,
                    backend_type=backend_type,
                    chat_id=chat_id,
                )
                await chat_repo.save_chat_by_id(fresh)
            except Exception as e:
                logger.exception("completion metadata failed: chat_id={} error={}", chat_id, e)

            # Safety net: a claude_code turn can end with a trailing user
            # message that was never confirmed delivered via the live steer
            # pipe (e.g. it raced turn-end teardown and _on_steer_detached
            # returned False). Don't finalize as done — relaunch a
            # continuation turn so the message isn't silently dropped forever
            # (see plan-2662-steer-race.md). codex/gemini/pi already
            # reconcile via their own status="steer" restart branch above.
            if backend_type == "claude_code" and result["status"] != "error" and not fresh.interrupted:
                confirmed_delivered = initial_msg_ids | set(all_consumed_steer_ids)
                has_undelivered_trailing = False
                for msg in reversed(fresh.messages):
                    if msg.role != "user":
                        break
                    if msg.id not in confirmed_delivered:
                        has_undelivered_trailing = True
                        break

                if has_undelivered_trailing:
                    logger.warning(
                        "steer reconciliation: chat_id={} undelivered trailing user message(s), relaunching turn",
                        chat_id,
                    )
                    complete_process(chat_id, status=result["status"])
                    await _relaunch_claude_code_turn(chat_id, user_id, proc)
                    return

            complete_process(chat_id, status=result["status"])

            # Mark as unread on successful completion
            if not fresh.interrupted and result["status"] != "error":
                from storage.repository.chat import set_chat_unread
                set_chat_unread(chat_id, True)

            # Telegram reply + post hooks (same for both backends)
            if not fresh.interrupted and result["status"] != "error":
                try:
                    from worker.runner import _consolidate_turn_images
                    if _consolidate_turn_images(fresh):
                        await chat_repo.save_chat_by_id(fresh)
                except Exception as e:
                    logger.exception("turn image consolidation failed: {}", e)

                try:
                    from worker.runner import _send_telegram_reply
                    if _send_telegram_reply(fresh, user_id, proc.get("trace_id"), vm_config=vm_config, ssh_client=client):
                        await chat_repo.save_chat_by_id(fresh)
                except Exception as e:
                    logger.exception("telegram reply failed: {}", e)

                post_hooks = proc.get("post_hooks")
                if post_hooks:
                    if isinstance(post_hooks, str):
                        post_hooks = json.loads(post_hooks)
                    from worker.runner import _run_post_hooks
                    _run_post_hooks(fresh, user_id, post_hooks, trace_id=proc.get("trace_id"))
        else:
            complete_process(chat_id, status=result["status"])

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


async def _apply_completion_metadata(fresh, result: dict, result_data: dict, proc: dict, backend_type: str, chat_id: str):
    """Persist backend completion metadata after running=False is durable."""
    from storage.entity.dto import Message
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    # Only persist the run's session/thread id back to chat.external_id
    # when the run's cwd matched chat.work_dir. Claude Code / Codex
    # session files are scoped per cwd, so a session created in a
    # mismatched cwd is unresumable from the chat's recorded work_dir
    # and would permanently break future resumes if written back.
    run_work_dir = proc.get("work_dir")
    cwd_matches = bool(run_work_dir) and (run_work_dir == fresh.work_dir)

    if backend_type == "codex":
        # Codex: usage from turn.completed event
        effective_thread_id = result.get("thread_id") or proc.get("session_id")
        if effective_thread_id:
            if cwd_matches:
                fresh.external_id = effective_thread_id
            else:
                logger.warning(
                    "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (codex thread_id={})",
                    chat_id, run_work_dir, fresh.work_dir, effective_thread_id,
                )
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
            fresh.messages.append(error_msg)
    elif backend_type == "gemini_cli":
        effective_session_id = result.get("session_id") or proc.get("session_id")
        if effective_session_id:
            if cwd_matches:
                fresh.external_id = effective_session_id
            else:
                logger.warning(
                    "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (gemini session_id={})",
                    chat_id, run_work_dir, fresh.work_dir, effective_session_id,
                )
        if result_data and not result_data.get("is_error"):
            usage = result_data.get("usage") or {}
            if not usage:
                stats = result_data.get("stats") or {}
                usage = {
                    "input_tokens": stats.get("input_tokens") or stats.get("inputTokens"),
                    "output_tokens": stats.get("output_tokens") or stats.get("outputTokens"),
                }
            if usage:
                fresh.input_tokens = usage.get("input_tokens")
                fresh.output_tokens = usage.get("output_tokens")

        if result["status"] == "error":
            error_text = (result_data.get("result") if result_data else None) or "Gemini CLI exited with an error."
            error_msg = Message(
                id=generate_message_id(),
                role="assistant",
                content=error_text,
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
            )
            fresh.messages.append(error_msg)
    elif backend_type == "pi_cli":
        effective_session_id = result.get("session_id") or proc.get("session_id")
        if effective_session_id:
            if cwd_matches:
                fresh.external_id = effective_session_id
            else:
                logger.warning(
                    "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (pi session_id={})",
                    chat_id, run_work_dir, fresh.work_dir, effective_session_id,
                )
        if result_data and not result_data.get("is_error"):
            usage = result_data.get("usage") or {}
            if usage:
                fresh.input_tokens = usage.get("input_tokens")
                fresh.output_tokens = usage.get("output_tokens")

        if result["status"] == "error":
            error_text = (result_data.get("result") if result_data else None) or "pi exited with an error."
            error_msg = Message(
                id=generate_message_id(),
                role="assistant",
                content=error_text,
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
            )
            fresh.messages.append(error_msg)
    elif backend_type == "claude_tui":
        # Claude Code TUI: usage comes straight from the final assistant record's
        # `message.usage` block (raw anthropic field names), not a `result` event.
        effective_session_id = result.get("session_id") or proc.get("session_id")
        if effective_session_id:
            if cwd_matches:
                fresh.external_id = effective_session_id
            else:
                logger.warning(
                    "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (claude_tui session_id={})",
                    chat_id, run_work_dir, fresh.work_dir, effective_session_id,
                )
        if result_data and not result_data.get("is_error"):
            usage = result_data.get("usage") or {}
            if usage:
                fresh.input_tokens = usage.get("input_tokens")
                fresh.output_tokens = usage.get("output_tokens")
                fresh.cache_read_input_tokens = usage.get("cache_read_input_tokens")
                fresh.cache_creation_input_tokens = usage.get("cache_creation_input_tokens")

        if result["status"] == "error":
            error_text = (result_data.get("result") if result_data else None) or "Claude Code TUI exited with an error."
            error_msg = Message(
                id=generate_message_id(),
                role="assistant",
                content=error_text,
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
            )
            fresh.messages.append(error_msg)
    else:
        # Claude Code: existing logic
        effective_session_id = result.get("session_id") or proc.get("session_id")
        if effective_session_id:
            if cwd_matches:
                fresh.external_id = effective_session_id
            else:
                logger.warning(
                    "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (claude session_id={})",
                    chat_id, run_work_dir, fresh.work_dir, effective_session_id,
                )

        if result_data:
            _apply_claude_usage(fresh, result_data)

            if result["status"] == "error":
                error_text = result_data.get("result") or "Claude Code exited with an error."
                error_msg = Message(
                    id=generate_message_id(),
                    role="assistant",
                    content=error_text,
                    timestamp=get_utc_iso8601_timestamp(),
                    unix_timestamp=get_unix_timestamp(),
                )
                fresh.messages.append(error_msg)


def _iter_model_usage_entries(model_usage):
    if isinstance(model_usage, dict):
        values = model_usage.values()
    elif isinstance(model_usage, list):
        values = model_usage
    else:
        return []
    return [entry for entry in values if isinstance(entry, dict)]


def _apply_claude_usage(fresh, result_data: dict):
    if not isinstance(result_data, dict):
        return

    model_usage = result_data.get("modelUsage", {})
    usage_entries = _iter_model_usage_entries(model_usage)
    if not usage_entries:
        return

    num_turns = result_data.get("num_turns") or 1
    if not isinstance(num_turns, int) or num_turns <= 0:
        num_turns = 1

    fresh.input_tokens = sum(_int_value(entry.get("inputTokens")) for entry in usage_entries) // num_turns
    fresh.output_tokens = sum(_int_value(entry.get("outputTokens")) for entry in usage_entries) // num_turns
    fresh.cache_read_input_tokens = sum(_int_value(entry.get("cacheReadInputTokens")) for entry in usage_entries) // num_turns
    fresh.cache_creation_input_tokens = sum(_int_value(entry.get("cacheCreationInputTokens")) for entry in usage_entries) // num_turns
    fresh.context_window = max((_int_value(entry.get("contextWindow")) for entry in usage_entries), default=None)


def _int_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _relaunch_claude_code_turn(chat_id: str, user_id: int, proc: dict) -> None:
    """Re-invoke the normal claude_code launch path for a leftover trailing
    user message that the steer race failed to deliver, instead of
    finalizing the turn as done (safety net, see plan-2662-steer-race.md).

    Reuses `run_chat` so this goes through the same resume-detection,
    tmux launch, and DynamoDB registration as any other turn — `resume` is
    computed from `chat.external_id` (already persisted by
    `_apply_completion_metadata` above) and `chat.work_dir`.
    """
    from worker.runner import run_chat

    post_hooks = proc.get("post_hooks")
    if isinstance(post_hooks, str):
        post_hooks = json.loads(post_hooks)

    await run_chat(
        user_id,
        chat_id,
        bot_name=proc.get("bot_name"),
        vm_name=proc.get("vm_name"),
        work_dir=proc.get("work_dir"),
        post_hooks=post_hooks,
        trace_id=proc.get("trace_id"),
        topic=proc.get("topic"),
        backend="claude_code",
    )


async def _sweep_orphan_running_chats():
    from storage.repository import chat as chat_repo

    try:
        running_process_ids = {proc["chat_id"] for proc in get_running_processes() if proc.get("chat_id")}
        cutoff_unix = int(time.time()) - ORPHAN_RUNNING_CHAT_GRACE_SECONDS
        orphan_chat_ids = chat_repo.find_running_chat_ids_older_than(cutoff_unix)
        for orphan_chat_id in orphan_chat_ids:
            if orphan_chat_id in running_process_ids:
                continue
            await _mark_chat_stopped(orphan_chat_id)
            logger.warning("swept orphan running chat: chat_id={}", orphan_chat_id)
    except Exception as e:
        logger.exception("orphan running chat sweep failed: {}", e)

    return


async def _restart_codex_with_steer(chat_id: str, proc: dict, result: dict):
    """Restart a steered codex run via `codex exec resume <thread_id>`.

    `codex exec` has no live-steer channel, so `tail_codex_output` kills the
    session and returns status="steer". Here we resume the codex thread with
    the steer text as the new prompt, reset the stdout offset (the file is
    truncated on restart), and release the lease so the next monitor pass
    tails the fresh process. The process row stays status=running.
    """
    from agent.config import resolve_vm_config, resolve_bot_config
    from agent.codex import start_detached_codex_ssh
    from worker.runner import build_codex_resume_cmd, build_codex_env, build_codex_provider_args

    thread_id = result.get("thread_id")
    if not thread_id:
        # No thread id means codex never reached thread.started — nothing to
        # resume. Treat it as a normal completion so the chat doesn't hang.
        logger.warning("codex steer: no thread_id for chat_id={}, cannot resume", chat_id)
        complete_process(chat_id, status="completed")
        await _mark_chat_stopped(chat_id)
        return

    user_id = proc["user_id"]
    work_dir = proc.get("work_dir")
    vm_config = resolve_vm_config(user_id, proc["vm_name"], work_dir=work_dir)
    bot_config = resolve_bot_config(user_id, proc.get("bot_name"), backend=proc.get("backend_type"))

    model = bot_config.model.strip('"').strip() if bot_config.model else None
    cmd = build_codex_resume_cmd(thread_id, model or None)
    # Keep the per-bot relay override on steer restarts; without it the resumed
    # run drops the -c provider flags and reverts to the host config.toml crs.
    cmd.extend(build_codex_provider_args(bot_config))

    last_message_id = result.get("last_message_id")
    env = build_codex_env(bot_config, chat_id, proc.get("trace_id"),
                          proc.get("topic"), last_message_id)

    await start_detached_codex_ssh(
        cmd=cmd,
        prompt=result.get("steer_text", ""),
        cwd=work_dir,
        chat_id=chat_id,
        vm_config=vm_config,
        env=env or None,
        images=result.get("steer_images") or None,
    )

    # Accumulate consumed steer ids across restarts so they aren't re-detected.
    prev_consumed = proc.get("consumed_steer_ids")
    if isinstance(prev_consumed, str):
        try:
            prev_consumed = json.loads(prev_consumed)
        except (json.JSONDecodeError, TypeError):
            prev_consumed = []
    all_consumed = list(prev_consumed or []) + list(result.get("consumed_steer_ids", []))

    # stdout file is truncated by the resumed run → reset offset to 0.
    update_process_offset(
        chat_id=chat_id,
        offset=0,
        last_message_id=last_message_id,
        session_id=thread_id,
        consumed_steer_ids=all_consumed,
    )
    release_lease(chat_id)
    logger.info("codex steer: restarted chat_id={} thread_id={}", chat_id, thread_id)


async def _restart_gemini_with_steer(chat_id: str, proc: dict, result: dict):
    """Restart a steered Gemini CLI run via `gemini --resume <session_id>`."""
    from agent.config import resolve_vm_config, resolve_bot_config
    from agent.gemini_cli import start_detached_gemini_ssh
    from worker.runner import build_gemini_resume_cmd, build_gemini_env

    session_id = result.get("session_id")
    if not session_id:
        logger.warning("gemini steer: no session_id for chat_id={}, cannot resume", chat_id)
        from storage.entity.dto import Message
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

        error_msg = Message(
            id=generate_message_id(),
            role="assistant",
            content=(
                "Gemini CLI could not resume the steer message because the current run "
                "did not emit a session id before it was interrupted. Please send the "
                "message again after starting a new run."
            ),
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        message_callback(chat_id, error_msg)
        complete_process(chat_id, status="error")
        await _mark_chat_stopped(chat_id)
        return

    user_id = proc["user_id"]
    work_dir = proc.get("work_dir")
    vm_config = resolve_vm_config(user_id, proc["vm_name"], work_dir=work_dir)
    bot_config = resolve_bot_config(user_id, proc.get("bot_name"), backend=proc.get("backend_type"))

    model = bot_config.model.strip('"').strip() if bot_config.model else None
    cmd = build_gemini_resume_cmd(session_id, model or None)

    last_message_id = result.get("last_message_id")
    env = build_gemini_env(bot_config, chat_id, proc.get("trace_id"),
                           proc.get("topic"), last_message_id)

    await start_detached_gemini_ssh(
        cmd=cmd,
        prompt=result.get("steer_text", ""),
        cwd=work_dir,
        chat_id=chat_id,
        vm_config=vm_config,
        env=env or None,
        images=result.get("steer_images") or None,
    )

    prev_consumed = proc.get("consumed_steer_ids")
    if isinstance(prev_consumed, str):
        try:
            prev_consumed = json.loads(prev_consumed)
        except (json.JSONDecodeError, TypeError):
            prev_consumed = []
    all_consumed = list(prev_consumed or []) + list(result.get("consumed_steer_ids", []))

    update_process_offset(
        chat_id=chat_id,
        offset=0,
        last_message_id=last_message_id,
        session_id=session_id,
        consumed_steer_ids=all_consumed,
    )
    release_lease(chat_id)
    logger.info("gemini steer: restarted chat_id={} session_id={}", chat_id, session_id)


async def _restart_pi_with_steer(chat_id: str, proc: dict, result: dict):
    """Restart a steered pi run via `pi --session <session_id>`."""
    from agent.config import resolve_vm_config, resolve_bot_config
    from agent.pi_cli import start_detached_pi_ssh
    from worker.runner import build_pi_resume_cmd, build_pi_env, resolve_pi_model_and_provider

    session_id = result.get("session_id")
    if not session_id:
        logger.warning("pi steer: no session_id for chat_id={}, cannot resume", chat_id)
        from storage.entity.dto import Message
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

        error_msg = Message(
            id=generate_message_id(),
            role="assistant",
            content=(
                "pi could not resume the steer message because the current run "
                "did not emit a session id before it was interrupted. Please send the "
                "message again after starting a new run."
            ),
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        message_callback(chat_id, error_msg)
        complete_process(chat_id, status="error")
        await _mark_chat_stopped(chat_id)
        return

    user_id = proc["user_id"]
    work_dir = proc.get("work_dir")
    vm_config = resolve_vm_config(user_id, proc["vm_name"], work_dir=work_dir)
    bot_config = resolve_bot_config(user_id, proc.get("bot_name"), backend=proc.get("backend_type"))

    model = bot_config.model.strip('"').strip() if bot_config.model else None
    api_key = bot_config.api_key or None
    # Mirror _build_pi_params: a base_url bot resumes via its custom provider
    # (`y-<bot>/<model>`, auth in models.json) so the resume cmd matches the
    # original launch and the provider entry is re-written before relaunch.
    model, models_provider = resolve_pi_model_and_provider(bot_config, model or None)
    if models_provider:
        api_key = None
    cmd = build_pi_resume_cmd(session_id, model or None, api_key)

    last_message_id = result.get("last_message_id")
    env = build_pi_env(bot_config, chat_id, proc.get("trace_id"),
                       proc.get("topic"), last_message_id)

    await start_detached_pi_ssh(
        cmd=cmd,
        prompt=result.get("steer_text", ""),
        cwd=work_dir,
        chat_id=chat_id,
        vm_config=vm_config,
        env=env or None,
        images=result.get("steer_images") or None,
        models_provider=models_provider,
    )

    prev_consumed = proc.get("consumed_steer_ids")
    if isinstance(prev_consumed, str):
        try:
            prev_consumed = json.loads(prev_consumed)
        except (json.JSONDecodeError, TypeError):
            prev_consumed = []
    all_consumed = list(prev_consumed or []) + list(result.get("consumed_steer_ids", []))

    update_process_offset(
        chat_id=chat_id,
        offset=0,
        last_message_id=last_message_id,
        session_id=session_id,
        consumed_steer_ids=all_consumed,
    )
    release_lease(chat_id)
    logger.info("pi steer: restarted chat_id={} session_id={}", chat_id, session_id)


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
