"""Admin Lambda handler for database administration tasks."""

import json
import os

def lambda_handler(event, context):
    """Handle admin actions dispatched by CloudWatch schedules or manual invocation.

    Supported actions:
        init_db: Initialize database tables
        check_reminders: Send due reminders via Telegram
    """
    action = event.get("action", "")
    print(f"[admin] action={action} event={json.dumps(event)}")

    if action == "init_db":
        from storage.database.base import init_db, init_tables
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        init_db(database_url)
        init_tables()
        return {"status": "ok", "action": action}

    if action == "check_reminders":
        return _check_reminders()

    return {"status": "error", "message": f"Unknown action: {action}"}


def _check_reminders():
    """Query pending reminders that are due and send them via Telegram."""
    from storage.service import reminder as reminder_svc
    from storage.repository import user as user_repo
    from storage.util import get_telegram_bot_token, send_telegram_message

    bot_token = get_telegram_bot_token()
    if not bot_token:
        print("[check_reminders] TELEGRAM_BOT_TOKEN not set, skipping")
        return {"status": "skip", "action": "check_reminders", "reason": "no bot token"}

    pending = reminder_svc.get_pending_reminders()
    print(f"[check_reminders] found {len(pending)} due reminders")

    sent_count = 0
    errors = []
    for item in pending:
        user_id = item["user_id"]
        reminder = item["reminder"]

        user = user_repo.get_user_by_id(user_id)
        if not user or not user.telegram_id:
            print(f"[check_reminders] skip reminder {reminder.reminder_id}: user {user_id} has no telegram_id")
            continue

        text = f"\U0001f514 提醒: {reminder.title}"
        if reminder.description:
            text += f"\n{reminder.description}"

        try:
            send_telegram_message(bot_token, user.telegram_id, text)
            reminder_svc.mark_sent(user_id, reminder.reminder_id)
            sent_count += 1
            print(f"[check_reminders] sent reminder {reminder.reminder_id} to telegram_id {user.telegram_id}")
        except Exception as e:
            errors.append({"reminder_id": reminder.reminder_id, "error": str(e)})
            print(f"[check_reminders] error sending reminder {reminder.reminder_id}: {e}")

    result = {"status": "ok", "action": "check_reminders", "sent": sent_count, "total": len(pending)}
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    result = lambda_handler({"action": "init_db"}, None)
    # result = lambda_handler({"action": "check_reminders"}, None)
    print(result)
