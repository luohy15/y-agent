"""Admin Lambda handler for database administration tasks."""

import json
import os

from loguru import logger


def lambda_handler(event, context):
    """Handle admin actions dispatched by CloudWatch schedules or manual invocation.

    Supported actions:
        init_db: Initialize database tables
        check_reminders: Send due reminders through the gateway
        tick_routines: Fire due routines via the chat dispatch pipeline
        retry_access_notifications: Retry pending homepage-admission notices
        seed_access_rollout: Idempotently approve the maintainer and named account
    """
    action = event.get("action", "")
    logger.info("[admin] action={} event={}", action, json.dumps(event))

    if action == "init_db":
        from storage.database.base import init_db, init_tables
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        init_db(database_url)
        init_tables()
        return {"status": "ok", "action": action}

    if action == "check_reminders":
        return _check_reminders()

    if action == "todo_sla_digest":
        return _todo_sla_digest()

    if action == "sync_model_context_window":
        from storage.service.model_context import sync_missing_windows

        result = sync_missing_windows()
        absent = result["absent_from_catalog"]
        logger.info("[{}] checked={} inserted={} absent={} first_absent={}", action, result["models_checked"],
                    len(result["inserted"]), len(absent), [name[:128] for name in sorted(absent)[:20]])
        return {"status": "ok", "action": action, **result}

    if action == "tick_routines":
        return _tick_routines()

    if action == "retry_access_notifications":
        from storage.service.user_access import retry_notifications

        return retry_notifications()

    if action == "seed_access_rollout":
        from storage.service.user_access import seed_rollout

        return seed_rollout()

    return {"status": "error", "message": f"Unknown action: {action}"}


def _check_reminders():
    """Query pending reminders that are due and send them through the gateway."""
    from storage.service import gateway as gateway_service
    from storage.service import reminder as reminder_svc

    pending = reminder_svc.get_pending_reminders()
    logger.info("[check_reminders] found {} due reminders", len(pending))

    sent_count = 0
    errors = []
    for item in pending:
        user_id = item["user_id"]
        reminder = item["reminder"]

        text = f"\U0001f514 提醒: {reminder.title}"
        if reminder.description:
            text += f"\n{reminder.description}"

        try:
            result = gateway_service.send(user_id, text)
            if not result:
                logger.warning(
                    "[check_reminders] skip reminder {}: no channel",
                    reminder.reminder_id,
                )
                continue
            reminder_svc.mark_sent(user_id, reminder.reminder_id)
            sent_count += 1
            logger.info(
                "[check_reminders] sent reminder {} via {}",
                reminder.reminder_id,
                result.channel,
            )
        except Exception as e:
            errors.append({"reminder_id": reminder.reminder_id, "error": str(e)})
            logger.exception(
                "[check_reminders] error sending reminder {}: {}",
                reminder.reminder_id,
                e,
            )

    result = {"status": "ok", "action": "check_reminders", "sent": sent_count, "total": len(pending)}
    if errors:
        result["errors"] = errors
    return result


def _todo_sla_digest():
    from storage.repository import todo as todo_repo
    from storage.service import todo as todo_svc

    sent = 0
    errors = []
    for user_id in todo_repo.list_open_todo_user_ids():
        try:
            sent += int(todo_svc.notify_sla_digest(user_id))
        except Exception:
            logger.exception("[todo_sla_digest] failed for owner {}", user_id)
            errors.append("owner digest failed")
    return {"status": "error" if errors else "ok", "action": "todo_sla_digest",
            "sent": sent, "errors": errors}


def _tick_routines():
    """Fire enabled routines whose cron schedule is due."""
    from storage.service import gateway as gateway_service
    from storage.service import routine as routine_svc

    due = routine_svc.list_due_routines()
    logger.info("[tick_routines] found {} due routines", len(due))
    fired = 0
    skipped = 0
    errors = []
    for item in due:
        user_id = item["user_id"]
        routine = item["routine"]

        if routine.guard:
            try:
                if not routine_svc.evaluate_guard(user_id, routine.guard):
                    routine_svc.stamp_routine(user_id, routine.routine_id, "skipped: guard")
                    skipped += 1
                    logger.info(
                        "[tick_routines] guard rejected routine {} ({})",
                        routine.routine_id,
                        routine.name,
                    )
                    continue
            except Exception as e:
                logger.exception(
                    "[tick_routines] guard error routine={} guard={} err={}",
                    routine.routine_id,
                    routine.guard,
                    e,
                )

        try:
            chat_id = routine_svc.fire_routine(user_id, routine.routine_id)
            fired += 1
            logger.info(
                "[tick_routines] fired routine {} ({}) -> chat {}",
                routine.routine_id,
                routine.name,
                chat_id,
            )
        except Exception as e:
            errors.append({"routine_id": routine.routine_id, "error": str(e)})
            logger.exception(
                "[tick_routines] fire failed routine={} err={}",
                routine.routine_id,
                e,
            )
            try:
                if not gateway_service.send(user_id, f"⚠️ routine '{routine.name}' failed: {e}"):
                    logger.warning(
                        "[tick_routines] gateway skipped routine={}: no channel",
                        routine.routine_id,
                    )
            except Exception as notify_err:
                logger.exception(
                    "[tick_routines] gateway failed routine={} err={}",
                    routine.routine_id,
                    notify_err,
                )

    result = {"status": "ok", "action": "tick_routines", "fired": fired, "skipped": skipped, "total": len(due)}
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    result = lambda_handler({"action": "init_db"}, None)
    # result = lambda_handler({"action": "check_reminders"}, None)
    # result = lambda_handler({"action": "tick_routines"}, None)
    print(result)
