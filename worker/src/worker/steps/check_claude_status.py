"""Scheduled action: scan the Claude status RSS feed for active incidents and
notify the affected user via Telegram.

Runs on a 15-minute EventBridge cadence (same cadence as `fetch_rss_xml`). It
reads the already-fetched XML from S3 (depends on stage 1), parses each item,
extracts the latest status from the description HTML, and sends one Telegram
notification per (user, incident_guid) when an incident first appears and a
second one when it resolves. Dedup state lives in `claude_status_state`.

Notification-only by design: outage detection is good enough to alert the user
with a suggested `y bot update` command. Auto-degradation is out of scope.
"""

import asyncio
import re
from typing import Optional

import feedparser
from loguru import logger

from storage.service import claude_status_state as state_service
from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import rss_feed as rss_feed_service
from storage.service.telegram import resolve_target
from storage.util import send_telegram_message

from worker.link_downloader import s3_get


LOCK_NAME = "check_claude_status"

FEED_HOST = "status.claude.com"

# Latest status label inside the description HTML. The feed renders updates in
# chronological order; the last <strong>Label</strong> match is the current
# state.
STATUS_LABEL_RE = re.compile(
    r"<strong>(Investigating|Identified|Monitoring|Resolved)</strong>",
    re.IGNORECASE,
)

# Extract the affected model from the incident title, e.g. "Claude Opus 4.6".
MODEL_RE = re.compile(
    r"Claude\s+(Opus|Sonnet|Haiku|Fable|Mythos)\s+([\d.]+)",
    re.IGNORECASE,
)

ACROSS_MODELS_RE = re.compile(r"across\s+(?:all\s+)?models", re.IGNORECASE)

# Map model family -> currently configured bot names that route through Claude.
# Used to surface which local bot configs may be impacted and to suggest the
# right `y bot update` command. Hard-coded per plan; revisit when bot configs
# change.
MODEL_BOT_MAP: dict[str, list[str]] = {
    "opus": ["claude_code"],
    "sonnet": ["pi"],
    "haiku": [],
    "fable": [],
    "mythos": [],
}

ALL_CLAUDE_BOTS = ["claude_code", "pi"]


def _parse_latest_status(description_html: str) -> Optional[str]:
    if not description_html:
        return None
    matches = STATUS_LABEL_RE.findall(description_html)
    if not matches:
        return None
    return matches[-1].capitalize()


def _affected_bots(title: str) -> list[str]:
    if ACROSS_MODELS_RE.search(title or ""):
        return list(ALL_CLAUDE_BOTS)
    m = MODEL_RE.search(title or "")
    if not m:
        return []
    family = m.group(1).lower()
    return list(MODEL_BOT_MAP.get(family, []))


def _format_incident_msg(title: str, status: str, affected: list[str], pub_date: Optional[str]) -> str:
    lines = [
        f"[Claude Status] Active incident: \"{title}\"",
        f"Status: {status}" + (f" (since {pub_date})" if pub_date else ""),
    ]
    if affected:
        lines.append(f"Affected bot(s): {', '.join(affected)}")
        lines.append("")
        lines.append("Suggested action:")
        for bot in affected:
            if bot == "pi":
                lines.append(f"  y bot update {bot} -m anthropic/claude-haiku-4.5")
            else:
                lines.append(f"  y bot update {bot} -m claude-sonnet-4-6")
        lines.append("  # or redirect default to a non-Claude backend:")
        lines.append("  y bot update default --ref-bot-name pi")
    else:
        lines.append("Affected bot(s): none mapped (title model not recognized)")
    return "\n".join(lines)


def _format_resolved_msg(title: str, affected: list[str]) -> str:
    lines = [
        f"[Claude Status] Resolved: \"{title}\"",
    ]
    if affected:
        lines.append("If you degraded, restore with:")
        for bot in affected:
            lines.append(f"  y bot update {bot} -m \"\"")
    return "\n".join(lines)


def _send(user_id: int, text: str) -> bool:
    target = resolve_target(user_id, topic="manager")
    if not target:
        logger.warning("check_claude_status: no telegram target for user_id={}", user_id)
        return False
    bot_token, chat_id, thread_id = target
    try:
        send_telegram_message(bot_token, chat_id, text, message_thread_id=thread_id)
        return True
    except Exception:
        logger.exception("check_claude_status: telegram send failed user_id={}", user_id)
        return False


def _process_entry(user_id: int, entry) -> dict:
    guid = entry.get("id") or entry.get("guid") or entry.get("link")
    title = entry.get("title") or ""
    if not guid or not title:
        return {"skipped": "no_guid_or_title"}

    description = entry.get("description") or entry.get("summary") or ""
    status = _parse_latest_status(description)
    if not status:
        return {"guid": guid, "skipped": "no_status"}

    pub_date = entry.get("published") or entry.get("updated")

    prior = state_service.get_state(user_id, guid)
    prior_notified = bool(prior and prior.notified_at)
    prior_resolved_notified = bool(prior and prior.resolved_notified_at)

    state_service.upsert_state(user_id, guid, title, status)

    is_resolved = status.lower() == "resolved"
    affected = _affected_bots(title)
    notified = False
    resolved_notified = False

    if not is_resolved and not prior_notified:
        msg = _format_incident_msg(title, status, affected, pub_date)
        if _send(user_id, msg):
            state_service.mark_notified(user_id, guid)
            notified = True

    if is_resolved and prior_notified and not prior_resolved_notified:
        msg = _format_resolved_msg(title, affected)
        if _send(user_id, msg):
            state_service.mark_resolved_notified(user_id, guid)
            resolved_notified = True

    return {
        "guid": guid,
        "status": status,
        "affected": affected,
        "notified": notified,
        "resolved_notified": resolved_notified,
    }


def _process_feed(user_id: int, feed) -> dict:
    xml = s3_get(f"rss/{feed.rss_feed_id}.xml")
    if xml is None:
        return {"feed_id": feed.rss_feed_id, "skipped": "no_xml"}

    parsed = feedparser.parse(xml)
    if parsed.bozo and not parsed.entries:
        logger.warning(
            "check_claude_status parse warn feed={}: {}",
            feed.rss_feed_id, parsed.bozo_exception,
        )
        return {"feed_id": feed.rss_feed_id, "skipped": "bad_xml"}

    results = []
    for entry in parsed.entries:
        try:
            results.append(_process_entry(user_id, entry))
        except Exception as e:
            logger.exception(
                "check_claude_status entry error feed={}: {}",
                feed.rss_feed_id, e,
            )
            results.append({"error": str(e)})

    notified = sum(1 for r in results if r.get("notified"))
    resolved = sum(1 for r in results if r.get("resolved_notified"))
    logger.info(
        "check_claude_status feed={} user={} entries={} notified={} resolved={}",
        feed.rss_feed_id, user_id, len(results), notified, resolved,
    )
    return {
        "feed_id": feed.rss_feed_id,
        "entries": len(results),
        "notified": notified,
        "resolved_notified": resolved,
    }


async def handle_check_claude_status() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        logger.info("check_claude_status: lock held, skipping")
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}

    try:
        all_feeds = rss_feed_service.list_all_feeds()
        targets = [(uid, f) for uid, f in all_feeds if FEED_HOST in (f.url or "")]
        if not targets:
            logger.info("check_claude_status: no claude status feeds registered")
            return {"status": "ok", "action": LOCK_NAME, "feeds": 0}

        logger.info("check_claude_status: scanning {} feed(s)", len(targets))
        results = await asyncio.gather(
            *(asyncio.to_thread(_process_feed, uid, feed) for uid, feed in targets)
        )
        total_notified = sum(r.get("notified", 0) for r in results)
        total_resolved = sum(r.get("resolved_notified", 0) for r in results)
        return {
            "status": "ok",
            "action": LOCK_NAME,
            "feeds": len(targets),
            "notified": total_notified,
            "resolved_notified": total_resolved,
        }
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
