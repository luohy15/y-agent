"""Event loop that monitors detached tmux chat processes.

Shared by Lambda handler (with deadline_at from Lambda context) and Celery
worker (with deadline_at=None for local dev).
"""

import asyncio
import json
import os
import re
import time

from loguru import logger
from storage.role import legacy_topic_to_role, validate_role

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
    from agent.chat_target import layout
    from storage.service import chat as chat_service

    backend_type = proc.get("backend_type", "claude_code")
    user_id = proc["user_id"]
    offset = proc.get("stdout_offset", 0)
    last_message_id = proc.get("last_message_id")
    session_id = proc.get("session_id")

    # A disabled node still tails: this chat already lives there. An unknown
    # node fails closed instead of falling back to the orchestrator.
    node = layout(user_id, proc.get("target_id") or "default", allow_disabled=True)
    from storage.service.vm_config import touch_activity
    touch_activity(node.node, node.anchor)

    # Get pooled SSH client if pool is available. Jump nodes are a jump on it.
    client = ssh_pool.get_or_create(node) if ssh_pool else None

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
    # Build the steer checker. claude_code and pi forward a steer into the live
    # stdin pipe. Codex and agy have no live input channel: their tail ends the
    # running turn, and closeout relaunches the same thread with the message as
    # the prompt.
    from worker.runner import make_steer_checker
    steer_fn = make_steer_checker(chat_id, initial_msg_ids, previously_consumed=ledger.written_ids())

    logger.info("tail_and_process start chat_id={} offset={} backend={}", chat_id, offset, backend_type)

    from agent.claude_code import tail_ssh_output
    launch_input_uuid = next((native_uuid for native_uuid, ids in ledger.groups.items()
                              if proc.get("scope_first_id") in ids), None)
    if proc.get("closeout_pending"):
        result = _load_json_field(proc, "closeout_pending")
    elif proc.get("resume_pending"):
        result = json.loads(proc["resume_pending"])
    elif backend_type == "agy":
        from agent.agy import tail_agy_output
        result = await tail_agy_output(
            chat_id=chat_id,
            node=node,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
            ssh_client=client,
            input_ledger=ledger,
            launch_input_uuid=launch_input_uuid,
            pending_result=_load_json_field(proc, "pending_result") or None,
            conversation_id=proc.get("session_id"),
        )
    elif backend_type == "codex":
        from agent.codex import tail_codex_output
        result = await tail_codex_output(
            chat_id=chat_id,
            node=node,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
            ssh_client=client,
            input_ledger=ledger,
            launch_input_uuid=launch_input_uuid,
            pending_result=_load_json_field(proc, "pending_result") or None,
            resume_thread_id=proc.get("resume_thread_id"),
            model=proc.get("model"),
        )
    elif backend_type == "pi":
        from agent.pi_cli import tail_pi_output
        result = await tail_pi_output(
            chat_id=chat_id,
            node=node,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            check_steer_fn=steer_fn,
            ssh_client=client,
            input_ledger=ledger,
            launch_input_uuid=launch_input_uuid,
            pending_result=_load_json_field(proc, "pending_result") or None,
            session_id=proc.get("session_id"),
        )
    else:
        result = await tail_ssh_output(
            chat_id=chat_id,
            node=node,
            offset=offset,
            last_message_id=last_message_id,
            message_callback=_msg_callback,
            check_interrupted_fn=_check_interrupted,
            check_deadline_fn=_check_deadline,
            ssh_client=client,
            check_steer_fn=steer_fn,
            input_ledger=ledger,
            launch_input_uuid=launch_input_uuid,
            pending_result=_load_json_field(proc, "pending_result") or None,
            pending_context_usage=_load_json_field(proc, "pending_context_usage") or None,
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
        pending_context_usage=result.get("pending_context_usage"),
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
        if (backend_type == "claude_code" and _should_resume_5xx(result, proc)
                and updated_session_id and fresh and not fresh.interrupted):
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
                chat_id, user_id, proc,
                resume_5xx_retries=int(proc.get("resume_5xx_retries", 0)) + 1,
                run_seq=fresh.run_seq,
                continuation_from_id=proc.get("scope_first_id"),
                handled_input_ids=settled.handled_ids(),
            )
            return

        if backend_type == "codex" and result.get("status") == "error" and fresh:
            from agent.codex import codex_retry_decision
            from worker.death_delivery import current_run as _current_run
            decision = codex_retry_decision(
                stderr=result.get("attempt_stderr"),
                attempted_id=proc.get("resume_thread_id"),
                exit_code=result.get("exit_code"),
                has_usable_output=bool(result.get("has_usable_output")),
                retries=int(proc.get("codex_refusal_retries") or 0),
                interrupted=bool(fresh.interrupted),
                stale_run=not _current_run(chat_id, proc),
            )
            if decision == "retry" and fresh.external_id == proc.get("resume_thread_id"):
                from worker.process_manager import claim_codex_refusal_retry
                if not claim_codex_refusal_retry(chat_id, proc, lambda_req_id):
                    return
                logger.warning(
                    "codex missing rollout: chat_id={} thread_id={} diagnostic={}",
                    chat_id, proc.get("resume_thread_id"), result.get("startup_diagnostic"),
                )
                retry_result = {
                    **result,
                    "status": "completed",
                    "clear_refused_thread": True,
                    "refused_thread_id": proc.get("resume_thread_id"),
                }
                fresh = await persist_terminal(chat_id, proc, retry_result, outcome=None)
                if not fresh or fresh.interrupted or not retry_result.get("refused_cleared"):
                    return
                await _relaunch_claude_code_turn(
                    chat_id, user_id, proc,
                    resume_5xx_retries=int(proc.get("resume_5xx_retries") or 0),
                    run_seq=fresh.run_seq,
                    continuation_from_id=proc.get("scope_first_id"),
                    handled_input_ids=settled.handled_ids(),
                    codex_refusal_retries=int(proc.get("codex_refusal_retries") or 0) + 1,
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
            codex_turn = None
            if backend_type == "codex":
                codex_turn = _prepare_codex_turn_usage(user_id, chat_id, result, proc, client)
            agy_turn = None
            if backend_type == "agy":
                agy_turn = _prepare_agy_turn_usage(user_id, chat_id, result, proc)

            def _apply_metadata(chat):
                try:
                    _apply_completion_metadata(
                        fresh=chat,
                        result=result,
                        result_data=result.get("result_data"),
                        proc=proc,
                        chat_id=chat_id,
                        codex_turn=codex_turn,
                        agy_turn=agy_turn,
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

            if backend_type == "codex":
                _record_codex_turn_usage(user_id, fresh, codex_turn)
            elif backend_type == "agy":
                _record_agy_turn_usage(user_id, fresh, agy_turn)
                if agy_turn:
                    _rollup_agy_usage(user_id, chat_id)

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
                    trace_id=proc.get("trace_id"), role=validate_role(proc.get("role") or legacy_topic_to_role(proc.get("topic"))),
                    run_seq=run_seq,
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

            if not fresh.interrupted and result["status"] != "error":
                try:
                    from worker.runner import _consolidate_turn_images
                    _consolidate_turn_images(fresh)
                except Exception as e:
                    logger.exception("turn image consolidation failed: {}", e)

                try:
                    from worker.runner import _deliver_manager_reply
                    _deliver_manager_reply(fresh, user_id, vm_config=node.anchor, ssh_client=client)
                except Exception as e:
                    logger.exception("manager reply failed: {}", e)

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

                # A normal closeout reconciles its trace right away (todo 4077);
                # the scheduled watchdog stays the abnormal-recovery fallback.
                if result["status"] == "completed":
                    try:
                        from worker.session_end import reconcile_session_end, should_reconcile
                        if should_reconcile(fresh):
                            await reconcile_session_end(user_id, fresh)
                    except Exception as e:
                        logger.exception("session-end reconcile failed: chat_id={} error={}", chat_id, e)

            await _trigger_context_ingest(
                node, backend_type,
                (result.get("result_data") or {}).get("session_id") or updated_session_id,
            )
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


def _resolved_codex_model(proc: dict, chat):
    """Configured bot model, or None when it cannot be resolved.

    None means leave any stored window alone. A resolved name that has no
    declared window is what clears one.
    """
    user_id = proc.get("user_id")
    bot_name = proc.get("bot_name") or getattr(chat, "bot_name", None)
    if not user_id or not isinstance(bot_name, str) or not bot_name:
        return None
    try:
        from storage.service import bot_config

        config = bot_config.get_config(user_id, bot_name)
    except Exception as exc:
        logger.warning(
            "codex context window lookup failed: chat_id={} error={}",
            getattr(chat, "id", None), type(exc).__name__,
        )
        return None
    model = getattr(config, "model", None) if config else None
    if not isinstance(model, str):
        return None
    name = model.strip().strip('"').strip()
    return name or None


def _codex_usage_state(counters: dict) -> str:
    present = any(counters.get(name) is not None for name in (
        "input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens",
    ))
    return "observed" if present else "missing"


def _prepare_codex_turn_usage(user_id: int, chat_id: str, result: dict, proc: dict, client):
    """Turn delta, thread total and rollout window for one successful Codex turn.

    A failure returns None and leaves the stored badge alone. A missing rollout
    is not a failure: the table remains the window fallback.
    """
    data = result.get("result_data")
    if (result.get("status") != "completed" or not isinstance(data, dict)
            or data.get("type") != "turn.completed" or data.get("is_error")):
        return None
    try:
        from datetime import datetime, timezone
        from agent.codex import normalize_usage, read_codex_rollout
        from storage.service import chat_request_usage

        session_id = result.get("thread_id") or result.get("session_id") or proc.get("session_id")
        started_at = proc.get("started_at")
        if not isinstance(session_id, str) or not session_id or not isinstance(started_at, (int, float)):
            logger.warning("codex usage missing identity: chat_id={}", chat_id)
            return None
        current = normalize_usage(data.get("usage"))
        counters = {name: current.get(name) for name in chat_request_usage.COUNTERS}
        request_id = f"codex-{chat_id}-{started_at}"
        anchor = chat_request_usage.previous_anchor(user_id, chat_id, session_id, request_id)
        delta, reason = chat_request_usage.turn_delta(counters, anchor)
        if reason == "regression":
            logger.warning("codex usage regression: chat_id={}", chat_id)
        rollout = read_codex_rollout(client, session_id) or {}
        request_usage = rollout.get("request_usage")
        if not isinstance(request_usage, dict) or request_usage.get("usage_state") != "observed":
            request_usage = None
        window = rollout.get("context_window")
        if type(window) is not int or window <= 0:
            window = None
        model = _resolved_codex_model(proc, type("_Chat", (), {"id": chat_id, "bot_name": None})())
        return {
            "delta": delta,
            "cumulative": counters,
            "request_usage": request_usage,
            "usage_at": rollout.get("usage_at"),
            "context_window": window,
            "usage_state": _codex_usage_state(delta),
            "session_id": session_id,
            "model": model,
            "requested_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "request_id": request_id,
        }
    except Exception as exc:
        logger.warning("codex usage prepare failed: chat_id={} error={}", chat_id, type(exc).__name__)
        return None


def _record_codex_turn_usage(user_id: int, chat, codex_turn):
    """Write the prepared delta. Does not recompute usage from the turn event."""
    if not codex_turn:
        return
    if not codex_turn.get("session_id") or not codex_turn.get("model"):
        logger.warning("codex usage missing identity: chat_id={}", chat.id)
        return
    try:
        from storage.service import chat_request_usage

        outcome = chat_request_usage.record_backend_turn(
            user_id=user_id,
            chat_id=chat.id,
            session_id=codex_turn["session_id"],
            model=codex_turn["model"],
            requested_at=codex_turn["requested_at"],
            request_id=codex_turn["request_id"],
            usage={**codex_turn["delta"], "usage_state": codex_turn["usage_state"]},
            cumulative=codex_turn["cumulative"],
            backend="codex",
        )
        if any(outcome["conflicts"].values()):
            logger.warning("codex usage identity conflict: chat_id={}", chat.id)
    except Exception as exc:
        logger.warning("codex usage write failed: chat_id={} error={}", chat.id, type(exc).__name__)


def _prepare_agy_turn_usage(user_id: int, chat_id: str, result: dict, proc: dict):
    """Turn delta, conversation total and final-request occupancy for one agy turn.

    `result.usage` totals the whole conversation (verified on agy 1.5.17: turn 2
    reports turn 1 plus itself), so it is stored as the cumulative side and
    reduced against this thread's previous row. A failure returns None and
    leaves the stored badge alone.
    """
    data = result.get("result_data")
    if result.get("status") != "completed":
        return None
    try:
        from datetime import datetime, timezone
        from agent.agy import normalize_usage, successful_result
        from storage.service import bot_config, chat_request_usage

        inner = successful_result(data)
        if inner is None:
            return None
        session_id = (result.get("conversation_id") or result.get("session_id")
                      or proc.get("session_id"))
        started_at = proc.get("started_at")
        if not isinstance(session_id, str) or not session_id or not isinstance(started_at, (int, float)):
            logger.warning("agy usage missing identity: chat_id={}", chat_id)
            return None
        config = bot_config.get_config(user_id, proc.get("bot_name"))
        raw_model = getattr(config, "model", None) if config else None
        model = raw_model.strip('"').strip() if isinstance(raw_model, str) else ""
        if not model:
            logger.warning("agy usage missing identity: chat_id={}", chat_id)
            return None
        current = normalize_usage(inner.get("usage"))
        counters = {name: current.get(name) for name in chat_request_usage.COUNTERS}
        request_id = f"agy-{chat_id}-{started_at}"
        anchor = chat_request_usage.previous_anchor(user_id, chat_id, session_id, request_id)
        delta, reason = chat_request_usage.turn_delta(counters, anchor)
        if reason == "regression":
            logger.warning("agy usage regression: chat_id={}", chat_id)
        request_usage = result.get("request_usage")
        if not isinstance(request_usage, dict) or request_usage.get("usage_state") != "observed":
            request_usage = None
        return {
            "delta": delta,
            "cumulative": counters,
            "request_usage": request_usage,
            "usage_state": "observed" if any(v is not None for v in delta.values()) else "missing",
            "session_id": session_id,
            "model": model,
            "requested_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "request_id": request_id,
        }
    except Exception as exc:
        logger.warning("agy usage prepare failed: chat_id={} error={}", chat_id, type(exc).__name__)
        return None


def _record_agy_turn_usage(user_id: int, chat, agy_turn):
    """Write the prepared delta. Does not recompute usage from the result event."""
    if not agy_turn:
        return
    try:
        from storage.service import chat_request_usage

        outcome = chat_request_usage.record_backend_turn(
            user_id=user_id,
            chat_id=chat.id,
            session_id=agy_turn["session_id"],
            model=agy_turn["model"],
            requested_at=agy_turn["requested_at"],
            request_id=agy_turn["request_id"],
            usage={**agy_turn["delta"], "usage_state": agy_turn["usage_state"]},
            cumulative=agy_turn["cumulative"],
            backend="agy",
        )
        if any(outcome["conflicts"].values()):
            logger.warning("agy usage identity conflict: chat_id={}", chat.id)
    except Exception as exc:
        logger.warning("agy usage write failed: chat_id={} error={}", chat.id, type(exc).__name__)


def _rollup_agy_usage(user_id: int, chat_id: str) -> None:
    """Recompute this owner's `source='agy'` model_usage rows after a turn.

    Best-effort and isolated: the 5-minute scheduled sync is the backstop, so a
    failure here must not affect closeout. Makes a fresh agy turn visible in Bot
    Usage Live immediately, even while the relay is unreachable (todo 4465).
    """
    try:
        from storage.service import model_usage_backend

        model_usage_backend.sync_backend(user_id, "agy")
    except Exception as exc:
        logger.warning("agy usage rollup failed: chat_id={} error={}", chat_id, type(exc).__name__)


async def _trigger_context_ingest(node, backend_type: str, session_id):
    """Launch a scoped ingest after closeout; the hourly scan remains the backstop.

    Transcripts live on the node. Jump-node transcripts are not copied back in
    v1, so only a direct VM node ingests.
    """
    if not node.ingest_transcripts:
        return
    if (backend_type != "claude_code" or not isinstance(session_id, str)
            or not re.fullmatch(r"[0-9a-fA-F-]{36}", session_id)):
        return
    try:
        from agent.vm_command import execute_vm_command

        await asyncio.wait_for(execute_vm_command(
            node.anchor,
            ["sh", "-c", "mkdir -p ~/.y-agent/logs && "
             f"(nohup y usage ingest-transcripts --session {session_id} "
             "</dev/null >>~/.y-agent/logs/context-ingest.log 2>&1 &)"],
            wake=False, timeout=10, check=True,
        ), timeout=10)
    except Exception as exc:
        logger.warning("context ingest launch failed: {}", type(exc).__name__)


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


def _apply_completion_metadata(fresh, result: dict, result_data: dict, proc: dict, chat_id: str,
                              codex_turn=None, agy_turn=None):
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
    if proc.get("backend_type") == "codex":
        _apply_codex_completion(
            fresh, result, result_data, proc, chat_id, cwd_matches, codex_turn=codex_turn,
        )
        return

    if proc.get("backend_type") == "pi":
        session_id = result.get("session_id") or proc.get("session_id")
        if session_id and cwd_matches:
            fresh.external_id = session_id
        _apply_pi_context_usage(fresh, result)
        return

    if proc.get("backend_type") == "agy":
        _apply_agy_completion(
            fresh, result, result_data, proc, chat_id, cwd_matches, agy_turn=agy_turn,
        )
        return

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
        # `_claude_build_exec` restores a pruned session file by session ID from
        # lifelog/sessions/claude-code/projects *before* launching on the default
        # node, preserving its backup project directory. Jump nodes have no restore.
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
        _apply_claude_usage(fresh, result_data, result.get("context_usage"))

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
        values = model_usage.items()
    elif isinstance(model_usage, list):
        values = ((None, entry) for entry in model_usage)
    else:
        return []
    return [
        (name, entry) for name, entry in values if isinstance(entry, dict)
    ]


def _usage_iterations(result_data: dict):
    usage = result_data.get("usage")
    if not isinstance(usage, dict):
        return []
    iterations = usage.get("iterations")
    if not isinstance(iterations, list):
        return []
    return [entry if isinstance(entry, dict) else {"state": "unknown"} for entry in iterations]


def _context_window_for_usage(result_data: dict, usage: dict):
    """Window of the model that served this request.

    A side model such as the title model has the smaller window, so the max
    would overstate a request the main model served. Prefer the request's own
    model name, then the launch's declared model. On a cumulative 2.1.280
    result a side model's running total can outgrow one main request, so an
    unmatched request keeps the largest window rather than no window: no
    window disables the handoff reminder.
    """
    entries = _iter_model_usage_entries(result_data.get("modelUsage"))
    if not entries:
        return None
    for candidate in (usage.get("model"), result_data.get("model")):
        if not isinstance(candidate, str):
            continue
        for name, entry in entries:
            if name == candidate or entry.get("canonicalModel") == candidate:
                window = _int_value(entry.get("contextWindow"))
                if window:
                    return window
    return max(
        (_int_value(entry.get("contextWindow")) for _, entry in entries),
        default=0,
    ) or None


def _launch_average_usage(result_data: dict):
    """Average of this launch when no single request was observed.

    Relay-backed models stream assistant usage as zeroes and leave
    result.usage.iterations empty, so there is no per-request record.
    result.usage is the current launch on both 2.1.259 and 2.1.280, unlike
    modelUsage, which 2.1.280 accumulates across resumed launches. Dividing
    it by this launch's num_turns is an average, not the live context, but
    it stays on the right side of the handoff line for these models.
    """
    usage = result_data.get("usage")
    if not isinstance(usage, dict):
        return None
    counts = {
        "input_tokens": _int_value(usage.get("input_tokens")),
        "output_tokens": _int_value(usage.get("output_tokens")),
        "cache_read_input_tokens": _int_value(usage.get("cache_read_input_tokens")),
        "cache_creation_input_tokens": _int_value(usage.get("cache_creation_input_tokens")),
    }
    if not any(counts.values()):
        return None
    turns = result_data.get("num_turns")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns <= 0:
        turns = 1
    return {key: value // turns for key, value in counts.items()}


def _latest_complete_request(result_data: dict, observed_usage: dict):
    """Latest complete main-model request, independent of modelUsage scope.

    Claude Code 2.1.259 scopes modelUsage to the current launch; 2.1.280 can
    make it cumulative across resumed launches while usage and num_turns stay
    launch-scoped. Neither modelUsage aggregate divided by num_turns is the
    live context. The result event's final usage iteration is that request
    when the CLI emits one. Otherwise it is the last complete main-model
    assistant event, which the tail carries across a handoff because the
    finishing invocation only reads the unread tail of stdout. A launch with
    neither falls back to the launch-scoped average above.
    """
    iterations = _usage_iterations(result_data)
    if iterations:
        return iterations[-1]
    from agent.claude_code import _is_context_usage
    if _is_context_usage(observed_usage):
        return observed_usage
    return _launch_average_usage(result_data)


def _usage_stamp(value):
    if not isinstance(value, dict) or value.get("state") == "unknown":
        return None
    if value.get("timestamp_conflict") or value.get("timestamp_unbound"):
        return None
    stamp = value.get("requested_at")
    return stamp if isinstance(stamp, str) and stamp else None


_PROMPT_STAMP_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _prompt_stamp_counters(value):
    if not isinstance(value, dict):
        return None
    counters = []
    for key in _PROMPT_STAMP_KEYS:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        counters.append(item)
    return tuple(counters)


def _selected_usage_stamp(iterations, observed_usage):
    """Timestamp that belongs to the selected measurement.

    An iteration timestamp is its own. Without one, the latest complete assistant
    observation's first event time is used only when the prompt counters are the
    same request. Output is not part of that match. A message id alone, an earlier
    observation, and result-envelope durations are not substitutes.
    """
    if not iterations:
        return _usage_stamp(observed_usage)
    last = iterations[-1]
    if not isinstance(last, dict):
        return None
    own = last.get("timestamp")
    if isinstance(own, str) and own:
        return own
    if _prompt_stamp_counters(last) != _prompt_stamp_counters(observed_usage):
        return None
    return _usage_stamp(observed_usage)


def _apply_codex_completion(fresh, result: dict, result_data: dict, proc: dict, chat_id: str,
                            cwd_matches: bool, codex_turn=None):
    """Persist a Codex thread id and turn.completed usage, including its time."""
    from agent.codex import CODEX_CONTINUITY_NOTE, clear_refused_thread_id, format_codex_turn_failure
    from storage.entity.dto import Message
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    if result.get("clear_refused_thread"):
        if fresh.interrupted:
            result["refused_cleared"] = False
            return
        new_id, cleared = clear_refused_thread_id(
            fresh.external_id, result.get("refused_thread_id"), proc.get("resume_thread_id"),
        )
        result["refused_cleared"] = cleared
        if not cleared:
            # The successor reservation was taken before this check. Put it
            # back so a newer thread id is neither cleared nor relaunched.
            fresh.running = False
            if fresh.run_seq:
                fresh.run_seq -= 1
            logger.warning(
                "skip codex thread clear: chat_id={} external_id={} refused={} attempted={}",
                chat_id, fresh.external_id, result.get("refused_thread_id"), proc.get("resume_thread_id"),
            )
            return
        logger.warning(
            "clearing refused codex thread: chat_id={} thread_id={}",
            chat_id, fresh.external_id,
        )
        fresh.external_id = new_id
        fresh.messages.append(Message(
            id=generate_message_id(),
            role="assistant",
            content=CODEX_CONTINUITY_NOTE,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        ))
        return

    # A refusal echoes the dead id. Never write it back, even when this run
    # does not clear the column (interrupt, ceiling, or a lost claim).
    if result.get("resume_refused"):
        effective_thread_id = None
    else:
        effective_thread_id = result.get("thread_id") or result.get("session_id") or proc.get("session_id")
    if effective_thread_id:
        if cwd_matches:
            fresh.external_id = effective_thread_id
        else:
            logger.warning(
                "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (codex thread_id={})",
                chat_id, proc.get("work_dir"), fresh.work_dir, effective_thread_id,
            )
    if (codex_turn and isinstance(result_data, dict) and result_data.get("type") == "turn.completed"
            and not result_data.get("is_error")):
        # A missing prepare must not store the thread total as current context.
        request_usage = codex_turn.get("request_usage")
        observed_request = (
            isinstance(request_usage, dict) and request_usage.get("usage_state") == "observed"
        )
        badge = request_usage if observed_request else (codex_turn.get("delta") or {})
        fresh.input_tokens = badge.get("input_tokens")
        fresh.output_tokens = badge.get("output_tokens")
        fresh.cache_read_input_tokens = badge.get("cache_read_tokens")
        fresh.cache_creation_input_tokens = badge.get("cache_creation_tokens")
        cumulative = codex_turn.get("cumulative") or {}
        fresh.cumulative_input_tokens = cumulative.get("input_tokens")
        fresh.cumulative_output_tokens = cumulative.get("output_tokens")
        fresh.cumulative_cache_read_input_tokens = cumulative.get("cache_read_tokens")
        fresh.cumulative_cache_creation_input_tokens = cumulative.get("cache_creation_tokens")
        # NULL provenance is the legacy Claude fallback and would prepend the
        # handoff reminder. Only observed rollout occupancy is prompt context;
        # a turn delta is not and stays silent.
        fresh.context_usage_source = "codex_request" if observed_request else "codex_turn"
        # Bind the age to the winning rollout line's own time, never to the
        # turn start or the closeout clock.
        usage_at = codex_turn.get("usage_at")
        fresh.context_usage_requested_at = (
            usage_at if observed_request and isinstance(usage_at, str) and usage_at else None
        )
        window = codex_turn.get("context_window")
        if type(window) is int and window > 0:
            fresh.context_window = window
        else:
            model = codex_turn.get("model")
            if isinstance(model, str) and model:
                try:
                    from storage.service import model_context

                    fresh.context_window = model_context.get_context_window(model)
                except Exception as exc:
                    logger.warning(
                        "codex context window query failed: chat_id={} error={}",
                        chat_id, type(exc).__name__,
                    )
    if result.get("status") == "error":
        error_text = (result_data.get("result") if isinstance(result_data, dict) else None) or "Codex exited with an error."
        if not isinstance(error_text, str) or not error_text.startswith("Codex "):
            error_text = format_codex_turn_failure(error_text if isinstance(error_text, str) else None)
        fresh.messages.append(Message(
            id=generate_message_id(),
            role="assistant",
            content=error_text,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        ))


def _apply_agy_completion(fresh, result: dict, result_data: dict, proc: dict, chat_id: str,
                          cwd_matches: bool, agy_turn=None):
    """Persist an agy conversation id, turn badge and error text.

    `context_usage_source` stays unset: the resume gate does not cover agy, so
    the badge is display only rather than trusted prompt occupancy.
    """
    from storage.entity.dto import Message
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

    effective_id = result.get("conversation_id") or result.get("session_id") or proc.get("session_id")
    if effective_id:
        if cwd_matches:
            fresh.external_id = effective_id
        else:
            logger.warning(
                "skip external_id update: chat_id={} run_work_dir={} chat_work_dir={} (agy conversation_id={})",
                chat_id, proc.get("work_dir"), fresh.work_dir, effective_id,
            )
    if agy_turn:
        # The final request's own counters are the closest thing to occupancy;
        # the turn delta is the fallback when no step usage survived a handoff.
        usage = agy_turn.get("request_usage") or agy_turn.get("delta") or {}
        fresh.input_tokens = usage.get("input_tokens")
        fresh.output_tokens = usage.get("output_tokens")
        fresh.cache_read_input_tokens = usage.get("cache_read_tokens")
        fresh.cache_creation_input_tokens = usage.get("cache_creation_tokens")
    if result.get("status") == "error":
        error_text = (result_data.get("result") if isinstance(result_data, dict) else None) or "Antigravity CLI exited with an error."
        fresh.messages.append(Message(
            id=generate_message_id(),
            role="assistant",
            content=error_text,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        ))


def _apply_pi_context_usage(fresh, result: dict):
    """Persist pi's final-request occupancy from this turn's last response.

    Only a completed turn with observed usage replaces the stored observation;
    a failed or unobserved turn leaves the previous one in place. Pi persists
    no context window, so this feeds the resume gate, not a badge.
    """
    if result.get("status") != "completed":
        return
    usage = result.get("context_usage")
    if not isinstance(usage, dict) or usage.get("usage_state") != "observed":
        return
    fresh.input_tokens = usage.get("input_tokens")
    fresh.output_tokens = usage.get("output_tokens")
    fresh.cache_read_input_tokens = usage.get("cache_read_tokens")
    fresh.cache_creation_input_tokens = usage.get("cache_creation_tokens")
    fresh.context_usage_source = "pi_request"
    observed_at = usage.get("observed_at")
    fresh.context_usage_requested_at = (
        observed_at if isinstance(observed_at, str) and observed_at else None
    )


def _apply_claude_usage(fresh, result_data: dict, observed_usage: dict = None):
    # NULL provenance is the only legacy fallback signal. Unknown and
    # average-only closeouts keep an explicit marker so a later decision
    # cannot revive an older stored request.
    fresh.context_usage_source = "unknown"
    fresh.context_usage_requested_at = None
    if not isinstance(result_data, dict):
        return

    entries = _iter_model_usage_entries(result_data.get("modelUsage"))
    if entries:
        # Cumulative modelUsage is session spend, and its scope depends on the
        # CLI version. Keep it apart from the live context below.
        fresh.cumulative_input_tokens = sum(
            _int_value(entry.get("inputTokens")) for _, entry in entries
        )
        fresh.cumulative_output_tokens = sum(
            _int_value(entry.get("outputTokens")) for _, entry in entries
        )
        fresh.cumulative_cache_read_input_tokens = sum(
            _int_value(entry.get("cacheReadInputTokens")) for _, entry in entries
        )
        fresh.cumulative_cache_creation_input_tokens = sum(
            _int_value(entry.get("cacheCreationInputTokens")) for _, entry in entries
        )

    iterations = _usage_iterations(result_data)
    request = iterations[-1] if iterations else observed_usage
    if isinstance(request, dict) and all(
        isinstance(request.get(key), int) and not isinstance(request[key], bool) and request[key] >= 0
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    ) and any(request.get(key, 0) for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
        fresh.context_usage_source = "main_request"
        fresh.context_usage_requested_at = _selected_usage_stamp(iterations, observed_usage)
    latest = _latest_complete_request(result_data, observed_usage)
    if latest is None:
        return
    fresh.input_tokens = _int_value(latest.get("input_tokens"))
    fresh.output_tokens = _int_value(latest.get("output_tokens"))
    fresh.cache_read_input_tokens = _int_value(latest.get("cache_read_input_tokens"))
    fresh.cache_creation_input_tokens = _int_value(latest.get("cache_creation_input_tokens"))
    fresh.context_window = _context_window_for_usage(result_data, latest)


def _int_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _relaunch_claude_code_turn(chat_id: str, user_id: int, proc: dict,
                                     resume_5xx_retries: int = 0, run_seq: int = None,
                                     continuation_from_id: str = None,
                                     handled_input_ids=None,
                                     codex_refusal_retries: int = 0) -> None:
    """Re-invoke the normal launch path for input the finished run still owes.

    Reuses `run_chat`. The relaunch reads `chat.backend`; it does not take a
    backend override. `run_seq` is the reservation the closeout took, so this
    launch and a duplicate queue delivery cannot both become the successor.
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
        role=validate_role(proc.get("role") or legacy_topic_to_role(proc.get("topic"))),
        resume_5xx_retries=resume_5xx_retries,
        run_seq=run_seq,
        continuation_from_id=continuation_from_id,
        handled_input_ids=handled_input_ids,
        codex_refusal_retries=codex_refusal_retries,
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
    from agent.chat_target import layout
    from storage.service import chat as chat_service

    from worker.death_delivery import current_run
    owner_chat = await chat_service.get_chat(proc["user_id"], chat_id)
    if (not owner_chat or (owner_chat.role != "manager" and owner_chat.trace_id != proc.get("trace_id"))
            or not current_run(chat_id, proc)):
        return

    # 1. Kill tmux session on the node
    user_id = proc["user_id"]
    try:
        node = layout(user_id, proc.get("target_id") or "default", allow_disabled=True)
        client = ssh_pool.get_or_create(node) if ssh_pool else None
        if client:
            from agent.detach import _tmux_kill_cmd
            client.exec_command(
                f"{_tmux_kill_cmd(chat_id, node=node)}; "
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
