"""Event loop that monitors detached tmux chat processes.

Shared by Lambda handler (with deadline_at from Lambda context) and Celery
worker (with deadline_at=None for local dev).
"""

import asyncio
import json
import os
import time

from loguru import logger

from agent.input_ledger import COMPLETED, InputLedger
from worker.process_manager import (
    get_running_processes, get_process, try_acquire_lease, renew_lease,
    update_process_offset, complete_process, complete_current_process, release_lease,
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
                    if try_acquire_lease(cid, lambda_req_id, started_at=proc.get("started_at")):
                        # Scan is eventually consistent; tail from a consistent re-read.
                        # started_at must still be the generation the lease was
                        # acquired for, otherwise a new run's put_item could be
                        # tailed under the previous generation's lease.
                        fresh = get_process(cid)
                        if (not fresh or fresh.get("status") != "running"
                                or fresh.get("started_at") != proc.get("started_at")):
                            logger.warning(
                                "skip stale monitor candidate: chat_id={} status={} started_at={} acquired_started_at={}",
                                cid, (fresh or {}).get("status"),
                                (fresh or {}).get("started_at"), proc.get("started_at"),
                            )
                            continue

                        # Hard timeout check: if process has been running too long, stop it
                        started_at = fresh.get("started_at", 0)
                        if (not fresh.get("closeout_pending") and started_at
                                and time.time() - started_at > HARD_TIMEOUT_SECONDS):
                            logger.warning("hard timeout: chat_id={} started_at={} elapsed={}s", cid, started_at, int(time.time() - started_at))
                            await _handle_timeout(cid, fresh, ssh_pool)
                            continue

                        proc_meta[cid] = fresh
                        task = asyncio.create_task(_tail_and_process(cid, fresh, lambda_req_id, deadline_at, ssh_pool))
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
                    current = get_process(cid)
                    if current.get("closeout_pending") and current.get("status") == "running":
                        # A durable arbitration/send retry is not a dead native
                        # process. Keep it discoverable across invocations.
                        logger.warning("closeout retry retained chat_id={}: {}", cid, e)
                        error_counts.pop(cid, None)
                        proc_meta.pop(cid, None)
                        continue
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
                        # Tail cancellation must join its reader/writer before
                        # another invocation can acquire the checkpoint.
                        await asyncio.gather(*pending, return_exceptions=True)
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


def _load_json_field(proc: dict, key: str):
    raw = proc.get(key)
    if not raw:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_input_ledger(chat_id: str, proc: dict) -> InputLedger:
    """Rebuild this run's input ledger from its process record.

    A record written before todo 3643 carries only `consumed_steer_ids`, whose
    meaning was "the SSH write returned 0". Those ids are seeded as completed so
    a run already in flight across the upgrade behaves exactly as it did before
    rather than being replayed.
    """
    states = _load_json_field(proc, "delivery_states")
    groups = _load_json_field(proc, "input_groups")
    if not states:
        legacy = _load_json_field(proc, "consumed_steer_ids")
        if isinstance(legacy, list):
            states = {message_id: COMPLETED for message_id in legacy if message_id}
    return InputLedger(chat_id, states, groups, bool(proc.get("lifecycle_observed")))




def _turn_message_patch(fresh) -> dict:
    """Per-message fields this turn's completion hooks may have changed."""
    patch = {}
    for msg in reversed(fresh.messages):
        if msg.role == "user":
            break
        if msg.id:
            patch[msg.id] = {
                "images": list(msg.images or []),
                "telegram_delivered_images": list(msg.telegram_delivered_images or []),
            }
    return patch


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
        message_callback(chat_id, msg, user_id=user_id)

    # Build steer checker. claude_code injects steer into the live stdin pipe,
    # which is the only delivery path now that the kill-and-resume backends are
    # gone.
    chat = await chat_service.get_chat(user_id, chat_id)
    initial_msg_count = proc.get("initial_msg_count", len(chat.messages) if chat else 0)
    initial_msg_ids = (set(_load_json_field(proc, "initial_message_ids"))
                       if "initial_message_ids" in proc else
                       {msg.id for msg in (chat.messages[:initial_msg_count] if chat else []) if msg.id})
    # Rebuild this run's input ledger from the process record, so a handoff
    # resumes the same per-input state instead of re-deriving it. Everything
    # already written stays claimed (never write an input twice); only the
    # ledger's own terminal states decide what still needs answering.
    ledger = _load_input_ledger(chat_id, proc)
    from worker.runner import make_steer_checker
    steer_fn = make_steer_checker(chat_id, initial_msg_ids, previously_consumed=ledger.written_ids())

    logger.info("tail_and_process start chat_id={} offset={} backend={}", chat_id, offset, backend_type)

    from agent.claude_code import tail_ssh_output
    if proc.get("closeout_pending"):
        result = _load_json_field(proc, "closeout_pending")
    elif proc.get("resume_pending"):
        result = json.loads(proc["resume_pending"])
    else:
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
            input_ledger=ledger,
            pending_result=_load_json_field(proc, "pending_result") or None,
        )

    if result["is_done"] and result["status"] != "error":
        from worker.process_manager import begin_closeout
        if not begin_closeout(chat_id, proc, result):
            return
        proc["closeout_pending"] = json.dumps(result)

    # Save offset to DynamoDB
    # Defensive: keep prior session_id when this tail did not observe a fresh one.
    updated_session_id = result.get("session_id") or session_id
    # The ledger the tail mutated is this run's authoritative delivery state; a
    # resume_pending replay carries none, so fall back to what was loaded.
    delivery_states = result.get("delivery_states") or ledger.states
    input_groups = result.get("input_groups") or ledger.groups
    lifecycle_observed = bool(result.get("lifecycle_observed", ledger.lifecycle_observed))
    settled = InputLedger(chat_id, delivery_states, input_groups, lifecycle_observed)
    update_process_offset(
        chat_id=chat_id,
        offset=result["offset"],
        last_message_id=result.get("last_message_id"),
        session_id=updated_session_id,
        delivery_states=delivery_states,
        input_groups=input_groups,
        lifecycle_observed=lifecycle_observed,
        pending_result=result.get("pending_result"),
        proc=proc,
        updates_offset=result.get("updates_offset"),
        has_usable_output=result.get("has_usable_output"),
    )

    if result["is_done"]:
        from storage.repository import chat as chat_repo
        fresh = await chat_service.get_chat(user_id, chat_id)
        from worker.death_delivery import current_run, persist_terminal, deliver_death
        if not current_run(chat_id, proc):
            return
        if _should_resume_5xx(result, proc) and updated_session_id and fresh and not fresh.interrupted:
            from agent.claude_code import _is_rate_limit_error_text
            from worker.process_manager import set_resume_pending, claim_resume
            if not proc.get("resume_pending"):
                delay = 30 if _is_rate_limit_error_text(result["result_data"].get("result")) else 0
                proc["resume_retry_at"] = time.time() + delay
                set_resume_pending(chat_id, proc, result, proc["resume_retry_at"])
            delay = max(0, proc["resume_retry_at"] - time.time())
            if deadline_at and time.monotonic() + delay + 30 >= deadline_at:
                release_lease(chat_id)
                return
            await asyncio.sleep(delay)
            fresh = await chat_service.get_chat(user_id, chat_id)
            from worker.death_delivery import current_run
            if not current_run(chat_id, proc):
                return
            if not fresh or fresh.interrupted:
                await persist_terminal(chat_id, proc, {"status": "interrupted"}, outcome="interrupted")
                return
            if not claim_resume(chat_id, proc, lambda_req_id):
                return
            fresh = await persist_terminal(chat_id, proc, {**result, "status": "completed"}, outcome=None)
            if not fresh or fresh.interrupted:
                return
            await _relaunch_claude_code_turn(
                chat_id, user_id, proc, backend=backend_type,
                resume_5xx_retries=int(proc.get("resume_5xx_retries", 0)) + 1,
                run_seq=fresh.run_seq,
                continuation_from_id=proc.get("scope_first_id"),
                handled_input_ids=settled.handled_ids(),
            )
            return

        if result["status"] == "error":
            fresh = await persist_terminal(chat_id, proc, result)
            if fresh:
                await deliver_death(chat_id, proc, "error", (result.get("result_data") or {}).get("result"))
            return

        # One closeout: retire this run's generation, then decide busy-vs-idle
        # under the chat row lock.
        if fresh:
            # closeout_pending already fences native tailing and remains
            # discoverable until arbitration and queue delivery succeed.
            def _apply_metadata(chat):
                try:
                    _apply_completion_metadata(
                        fresh=chat,
                        result=result,
                        result_data=result.get("result_data"),
                        proc=proc,
                        chat_id=chat_id,
                    )
                except Exception as e:
                    logger.exception("completion metadata failed: chat_id={} error={}", chat_id, e)

            fresh, pending_ids, run_seq = chat_repo.close_out_chat_run(
                user_id, chat_id,
                trace_id=proc.get("trace_id"),
                handled_ids=settled.handled_ids(),
                # New runs always reconcile the whole explicit input scope.
                # Only pre-upgrade records lack an anchor.
                scope_first_id=proc.get("scope_first_id"),
                scope_trailing=not proc.get("scope_first_id"),
                continuation_allowed=result["status"] != "error",
                apply_metadata=_apply_metadata,
                expected_run_seq=proc.get("run_seq"),
                closeout_id=str(proc["started_at"]),
                resume_5xx_retries=int(proc.get("resume_5xx_retries", 0)),
                post_hooks=proc.get("post_hooks"),
            )
            if not fresh:
                complete_current_process(chat_id, proc, result["status"])
                logger.info("closeout skipped chat_id={}: chat is not this run's to close", chat_id)
                return

            # The SQL receipt keeps this reservation and input subset durable.
            # Queue delivery may be retried; run claiming admits one backend.
            if pending_ids:
                logger.warning(
                    "closeout continuation: chat_id={} pending_inputs={} relaunching turn",
                    chat_id, pending_ids,
                )
                chat_service.send_chat_message(
                    chat_id, user_id=user_id, bot_name=proc.get("bot_name"),
                    vm_name=proc.get("vm_name"), work_dir=proc.get("work_dir"),
                    trace_id=proc.get("trace_id"), topic=proc.get("topic"),
                    backend=backend_type, run_seq=run_seq,
                )
                complete_current_process(chat_id, proc, result["status"])
                return

            if not complete_current_process(chat_id, proc, result["status"]):
                return

            # Mark as unread on successful completion, unless the turn already
            # signaled needs_attention (a stronger state a completion hook must
            # not downgrade).
            if not fresh.interrupted and result["status"] != "error":
                chat_service.mark_chat_completion_unread(user_id, chat_id)

            # Telegram reply + post hooks
            if not fresh.interrupted and result["status"] != "error":
                try:
                    from worker.runner import _consolidate_turn_images
                    _consolidate_turn_images(fresh)
                except Exception as e:
                    logger.exception("turn image consolidation failed: {}", e)

                try:
                    from worker.runner import _send_telegram_reply
                    _send_telegram_reply(fresh, user_id, proc.get("trace_id"), vm_config=vm_config, ssh_client=client)
                except Exception as e:
                    logger.exception("telegram reply failed: {}", e)

                # Both hooks only touch fields on this turn's own messages, so
                # carry those across instead of writing the whole snapshot back
                # over whatever has been accepted since the closeout.
                try:
                    chat_service.apply_message_patch_sync(chat_id, _turn_message_patch(fresh), user_id=user_id)
                except Exception as e:
                    logger.exception("turn message patch failed: chat_id={} error={}", chat_id, e)

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


def _should_resume_5xx(result: dict, proc: dict) -> bool:
    if result.get("status") != "error" or result.get("resume_refused"):
        return False
    if int(proc.get("resume_5xx_retries", 0)) >= 1:
        return False
    if proc.get("has_usable_output") or result.get("has_usable_output"):
        return False

    result_data = result.get("result_data")
    if not isinstance(result_data, dict) or not result_data.get("is_error"):
        return False
    from agent.claude_code import _is_retryable_api_error_text
    return _is_retryable_api_error_text(result_data.get("result"))


def _apply_completion_metadata(fresh, result: dict, result_data: dict, proc: dict, chat_id: str):
    """Persist backend completion metadata after running=False is durable."""
    from storage.entity.dto import Message
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    # Only persist the run's session id back to chat.external_id when the run's
    # cwd matched chat.work_dir. Claude Code session files are scoped per cwd,
    # so a session created in a mismatched cwd is unresumable from the chat's
    # recorded work_dir and would permanently break future resumes if written
    # back.
    run_work_dir = proc.get("work_dir")
    cwd_matches = bool(run_work_dir) and (run_work_dir == fresh.work_dir)

    effective_session_id = result.get("session_id") or proc.get("session_id")
    resume_refused = bool(result.get("resume_refused"))
    if resume_refused and cwd_matches and fresh.external_id:
        # Claude Code itself named the handle as the cause: "No conversation
        # found with session ID" in the run's own error result event
        # (`_result_event_resume_refused`, the shape a refusal actually takes) or
        # in its stderr (`_resume_refused`, the no-result fallback).
        # Drop it, otherwise every future turn retries the same dead handle and
        # the conversation is wedged forever (todo 2930's migrated chats, and
        # any chat whose session file is gone). Nothing recoverable is lost:
        # `_claude_build_exec` restores a pruned session file from the
        # assets/claude-code backup *before* launching, so a refusal means
        # neither copy exists for this work_dir.
        #
        # Gated on that affirmative signal and nothing else. Neither an error
        # status nor which branch the turn took is evidence about the handle:
        # `work_dir not found` never launches the CLI at all, an external
        # SIGTERM/SIGKILL may leave a perfectly live session, and a missing binary
        # / bad credentials / bad --model are CLI-level failures that hit every
        # chat at once (and a bad --model lands in the very same result-event
        # branch as a refusal) — inferring a refusal from any of that would turn a
        # transient outage into fleet-wide context loss.
        logger.warning(
            "clearing refused external_id: chat_id={} external_id={} work_dir={}",
            chat_id, fresh.external_id, fresh.work_dir,
        )
        fresh.external_id = None
    elif resume_refused:
        # Refused, but the clearing gate above did not apply — most importantly
        # because the handle was already cleared out of band (migration SQL) while
        # this turn was in flight. A refusal must never write a handle either way:
        # the refusal event echoes the refused id back as its own `session_id`, so
        # falling through to the persist branch would resurrect the dead id into
        # the column that was just cleaned, wedging the chat again.
        logger.warning(
            "skip external_id update: chat_id={} refused resume, nothing to persist "
            "(external_id={} run_work_dir={} chat_work_dir={} claude session_id={})",
            chat_id, fresh.external_id, run_work_dir, fresh.work_dir, effective_session_id,
        )
    elif effective_session_id:
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


async def _relaunch_claude_code_turn(chat_id: str, user_id: int, proc: dict, backend: str = "claude_code",
                                     resume_5xx_retries: int = 0, run_seq: int = None,
                                     continuation_from_id: str = None,
                                     handled_input_ids=None) -> None:
    """Re-invoke the normal launch path for input the finished run still owes.

    Reuses `run_chat` so this goes through the same resume-detection,
    tmux launch, and DynamoDB registration as any other turn — `resume` is
    computed from `chat.external_id` (already persisted by
    `_apply_completion_metadata` above) and `chat.work_dir`. `backend`
    defaults to `claude_code` but callers pass the actual backend_type so
    the relaunch stays on the same backend.

    `run_seq` is the reservation the closeout took, so this launch and a
    duplicate queue delivery cannot both become the successor.
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
        backend=backend,
        resume_5xx_retries=resume_5xx_retries,
        run_seq=run_seq,
        continuation_from_id=continuation_from_id,
        handled_input_ids=handled_input_ids,
    )


def _owner_process_running(user_id: int):
    """Fresh consistent lookup for the locked orphan-clear boundary; raises when unavailable."""
    def is_live(chat_id: str) -> bool:
        record = get_process(chat_id)
        return record.get("user_id") == user_id and record.get("status") == "running"
    return is_live


async def _sweep_orphan_running_chats() -> dict:
    """Owner-aware, paginated orphan maintenance; an evidence failure clears nothing.

    Runs at monitor start and from the scheduled `check_trace_liveness` action
    (todo 3458 S7b), so a chat stuck running with no process record is cleared
    even when no further monitor loop ever starts. The cutoff is in
    milliseconds like `chat.updated_at_unix`. The eventually consistent scan
    only shortlists candidates; each clear re-reads the process record
    consistently inside the row lock, and a candidate whose lookup fails is
    left running and counted as `failed`.
    """
    from storage.repository import chat as chat_repo
    from storage.util import get_unix_timestamp

    swept = failed = 0
    try:
        running = {(proc.get("user_id"), proc["chat_id"]) for proc in get_running_processes() if proc.get("chat_id")}
        cutoff_unix = get_unix_timestamp() - ORPHAN_RUNNING_CHAT_GRACE_SECONDS * 1000
        after_id = 0
        while True:
            page = chat_repo.find_running_chats_older_than(cutoff_unix, after_id=after_id)
            if not page:
                break
            after_id = page[-1][0]
            for _, user_id, chat_id in page:
                if (user_id, chat_id) in running:
                    continue
                try:
                    if chat_repo.stop_orphan_running_chat(user_id, chat_id, cutoff_unix, _owner_process_running(user_id)):
                        swept += 1
                        logger.warning("swept orphan running chat: user_id={} chat_id={}", user_id, chat_id)
                except Exception as e:
                    failed += 1
                    logger.warning("orphan sweep left chat running, evidence unavailable: user_id={} chat_id={} error={}",
                                   user_id, chat_id, e)
    except Exception as e:
        logger.exception("orphan running chat sweep failed: {}", e)
        return {"status": "error", "swept": swept, "failed": failed}
    return {"status": "degraded" if failed else "ok", "swept": swept, "failed": failed}


async def _handle_timeout(chat_id: str, proc: dict, ssh_pool=None):
    """Handle hard timeout through the same terminal persistence and delivery as errors."""
    from agent.config import resolve_vm_config
    from storage.service import chat as chat_service

    from worker.death_delivery import current_run
    owner_chat = await chat_service.get_chat(proc["user_id"], chat_id)
    if (not owner_chat or (owner_chat.topic != "manager" and owner_chat.trace_id != proc.get("trace_id"))
            or not current_run(chat_id, proc)):
        return

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

    from worker.death_delivery import persist_terminal, deliver_death
    elapsed = int(time.time() - proc.get("started_at", 0))
    timeout_text = f"This chat was automatically stopped after running for {elapsed // 60} minutes (hard timeout: {HARD_TIMEOUT_SECONDS // 60} min)."
    fresh = await persist_terminal(chat_id, proc, {
        "status": "error", "result_data": {"result": timeout_text},
    }, outcome="timeout")
    if fresh:
        await deliver_death(chat_id, proc, "timeout", timeout_text)

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
