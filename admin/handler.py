"""Admin Lambda handler for database administration tasks."""

import json
import os

from loguru import logger


def lambda_handler(event, context):
    """Handle admin actions dispatched by CloudWatch schedules or manual invocation.

    Supported actions:
        init_db: Initialize database tables
        check_reminders: Send due reminders via Telegram
        tick_routines: Fire due routines via the chat dispatch pipeline
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

    if action == "tick_routines":
        return _tick_routines()

    return {"status": "error", "message": f"Unknown action: {action}"}


def _check_reminders():
    """Query pending reminders that are due and send them via Telegram."""
    from storage.service import reminder as reminder_svc
    from storage.repository import user as user_repo
    from storage.util import get_telegram_bot_token, send_telegram_message

    bot_token = get_telegram_bot_token()
    if not bot_token:
        logger.warning("[check_reminders] TELEGRAM_BOT_TOKEN not set, skipping")
        return {"status": "skip", "action": "check_reminders", "reason": "no bot token"}

    pending = reminder_svc.get_pending_reminders()
    logger.info("[check_reminders] found {} due reminders", len(pending))

    sent_count = 0
    errors = []
    for item in pending:
        user_id = item["user_id"]
        reminder = item["reminder"]

        user = user_repo.get_user_by_id(user_id)
        if not user or not user.telegram_id:
            logger.warning(
                "[check_reminders] skip reminder {}: user {} has no telegram_id",
                reminder.reminder_id,
                user_id,
            )
            continue

        text = f"\U0001f514 提醒: {reminder.title}"
        if reminder.description:
            text += f"\n{reminder.description}"

        try:
            send_telegram_message(bot_token, user.telegram_id, text)
            reminder_svc.mark_sent(user_id, reminder.reminder_id)
            sent_count += 1
            logger.info(
                "[check_reminders] sent reminder {} to telegram_id {}",
                reminder.reminder_id,
                user.telegram_id,
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


def _tick_routines():
    """Fire enabled routines whose cron schedule is due."""
    from storage.service import routine as routine_svc
    from storage.repository import user as user_repo
    from storage.util import get_telegram_bot_token, send_telegram_message

    due = routine_svc.list_due_routines()
    logger.info("[tick_routines] found {} due routines", len(due))

    bot_token = get_telegram_bot_token()
    fired = 0
    errors = []
    for item in due:
        user_id = item["user_id"]
        routine = item["routine"]
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
            if not bot_token:
                continue
            user = user_repo.get_user_by_id(user_id)
            if not user or not user.telegram_id:
                continue
            try:
                send_telegram_message(
                    bot_token,
                    user.telegram_id,
                    f"⚠️ routine '{routine.name}' failed: {e}",
                )
            except Exception as notify_err:
                logger.exception(
                    "[tick_routines] telegram notify failed routine={} err={}",
                    routine.routine_id,
                    notify_err,
                )

    result = {"status": "ok", "action": "tick_routines", "fired": fired, "total": len(due)}
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    result = lambda_handler({"action": "init_db"}, None)
    # result = lambda_handler({"action": "check_reminders"}, None)
    # result = lambda_handler({"action": "tick_routines"}, None)
    print(result)
