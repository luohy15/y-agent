"""Admin Lambda handler for database administration tasks."""

import json
import os

def lambda_handler(event, context):
    """Handle admin actions dispatched by CloudWatch schedules or manual invocation.

    Supported actions:
        init_db: Initialize database tables
        check_reminders: Send due reminders via Telegram
        fetch_rss_feeds: Pull new items from all RSS feeds into the link table
        dispatch_link_downloads: Enqueue a batch of pending RSS-sourced links for download
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

    if action == "fetch_rss_feeds":
        return _fetch_rss_feeds()

    if action == "dispatch_link_downloads":
        return _dispatch_link_downloads(event.get("batch_size", 10))

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


def _fetch_rss_feeds():
    """Parse every rss_feed row and insert new items as link activities.

    New LinkEntity rows get source='rss'/source_feed_id=<feed>; pre-existing rows
    with source=NULL also get tagged. Downloads are NOT enqueued here — the
    dispatch_link_downloads action handles that to control fan-out.
    """
    import calendar
    import time
    from datetime import datetime, timezone

    import feedparser

    from storage.service import rss_feed as rss_feed_service
    from storage.service import link as link_service
    from storage.repository import link as link_repo

    feeds = rss_feed_service.list_all_feeds()
    print(f"[fetch_rss_feeds] scanning {len(feeds)} feeds")

    total_items = 0
    errors = []
    for user_id, feed in feeds:
        try:
            parsed = feedparser.parse(feed.url)
            if parsed.bozo and not parsed.entries:
                print(f"[fetch_rss_feeds] parse error feed={feed.rss_feed_id}: {parsed.bozo_exception}")
                errors.append({"feed_id": feed.rss_feed_id, "error": str(parsed.bozo_exception)})
                continue

            last_item_ts = feed.last_item_ts or 0
            max_ts = last_item_ts
            added = 0

            for entry in parsed.entries:
                url = entry.get("link")
                if not url:
                    continue
                ts_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                if not ts_struct:
                    continue  # skip undated items to avoid duplicate activities on re-fetch
                ts_ms = int(calendar.timegm(ts_struct) * 1000)
                if ts_ms <= last_item_ts:
                    continue

                title = entry.get("title")
                activity = link_service.add_link(user_id, url, title=title, timestamp=ts_ms)
                link_repo.set_link_source_if_null(activity.link_id, "rss", feed.rss_feed_id)
                added += 1
                if ts_ms > max_ts:
                    max_ts = ts_ms

            now_iso = datetime.now(timezone.utc).isoformat()
            rss_feed_service.update_fetch_state(
                feed.rss_feed_id,
                last_fetched_at=now_iso,
                last_item_ts=max_ts if max_ts > (feed.last_item_ts or 0) else None,
            )
            total_items += added
            print(f"[fetch_rss_feeds] feed={feed.rss_feed_id} user={user_id} added={added}")
        except Exception as e:
            errors.append({"feed_id": feed.rss_feed_id, "error": str(e)})
            print(f"[fetch_rss_feeds] error feed={feed.rss_feed_id}: {e}")

    result = {"status": "ok", "action": "fetch_rss_feeds", "feeds": len(feeds), "items": total_items}
    if errors:
        result["errors"] = errors
    return result


def _dispatch_link_downloads(batch_size: int = 10):
    """Pick up to `batch_size` pending RSS-sourced links and enqueue downloads.

    Keeps the fan-out bounded per tick so a large fetch doesn't blow up the
    worker with concurrent SSH sessions. Manual /api/link/download stays direct.
    """
    from storage.repository import link as link_repo
    from storage.service import link as link_service

    items = link_repo.list_pending_rss_links(batch_size)
    print(f"[dispatch_link_downloads] batch_size={batch_size} picked={len(items)}")

    dispatched = 0
    errors = []
    for item in items:
        try:
            results = link_service.request_downloads([item["base_url"]])
            for r in results:
                if r["download_status"] != "pending":
                    continue
                link_service.send_download_task(
                    item["user_id"], r["link_id"], r["url"],
                    activity_id=r.get("activity_id"),
                )
                dispatched += 1
                print(f"[dispatch_link_downloads] enqueued link={r['link_id']} user={item['user_id']} url={r['url']}")
        except Exception as e:
            errors.append({"link_id": item["link_id"], "error": str(e)})
            print(f"[dispatch_link_downloads] error link={item['link_id']}: {e}")

    result = {
        "status": "ok",
        "action": "dispatch_link_downloads",
        "picked": len(items),
        "dispatched": dispatched,
    }
    if errors:
        result["errors"] = errors
    return result


if __name__ == "__main__":
    result = lambda_handler({"action": "init_db"}, None)
    # result = lambda_handler({"action": "check_reminders"}, None)
    # result = lambda_handler({"action": "fetch_rss_feeds"}, None)
    # result = lambda_handler({"action": "dispatch_link_downloads"}, None)
    print(result)
