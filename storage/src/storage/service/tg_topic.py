"""Telegram topic service — CRUD + sync missing topics via Bot API."""

import os
from typing import List, Optional

import httpx
from loguru import logger

from storage.dto.tg_topic import TgTopic
from storage.repository import tg_topic as tg_topic_repo

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_DEV", os.getenv("TELEGRAM_BOT_TOKEN", ""))


def _bot_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def list_topics(user_id: int, group_id: int) -> List[TgTopic]:
    return tg_topic_repo.list_topics(user_id, group_id)


def add_topic(user_id: int, group_id: int, topic_name: str, topic_icon: Optional[str] = None) -> TgTopic:
    return tg_topic_repo.add_topic(user_id, group_id, topic_name, topic_icon=topic_icon)


def delete_topic(user_id: int, pk_id: int) -> bool:
    return tg_topic_repo.delete_topic(user_id, pk_id)


def get_topic_by_name(user_id: int, group_id: int, topic_name: str) -> Optional[TgTopic]:
    return tg_topic_repo.get_topic_by_name(user_id, group_id, topic_name)


def upsert_topic(user_id: int, group_id: int, topic_name: str,
                 tg_topic_id: Optional[int] = None, topic_icon: Optional[str] = None) -> TgTopic:
    return tg_topic_repo.upsert_topic(user_id, group_id, topic_name,
                                       tg_topic_id=tg_topic_id, topic_icon=topic_icon)


def import_topics(user_id: int, group_id: int,
                  topics: list) -> List[TgTopic]:
    """Batch import existing topics. Each item: {topic_name, topic_id?, topic_icon?}."""
    results = []
    for t in topics:
        dto = tg_topic_repo.upsert_topic(
            user_id, group_id,
            topic_name=t["topic_name"],
            tg_topic_id=t.get("topic_id"),
            topic_icon=t.get("topic_icon"),
        )
        results.append(dto)
    return results


def auto_discover_topic(user_id: int, group_id: int, tg_topic_id: int,
                        topic_name: Optional[str] = None) -> Optional[TgTopic]:
    """Record a topic discovered from a webhook message. Skip if already known."""
    existing = tg_topic_repo.get_topic_by_thread_id(user_id, group_id, tg_topic_id)
    if existing:
        return existing
    # Use provided name or a placeholder
    name = topic_name or f"topic-{tg_topic_id}"
    return tg_topic_repo.upsert_topic(user_id, group_id, name, tg_topic_id=tg_topic_id)


async def sync_topics(user_id: int, group_id: int) -> List[TgTopic]:
    """Create missing Telegram forum topics and update DB with returned topic_ids."""
    topics = tg_topic_repo.list_topics(user_id, group_id)
    pending = [t for t in topics if t.topic_id is None]
    if not pending:
        return topics

    async with httpx.AsyncClient() as client:
        for topic in pending:
            payload = {"chat_id": group_id, "name": topic.topic_name}
            if topic.topic_icon:
                payload["icon_custom_emoji_id"] = topic.topic_icon
            try:
                resp = await client.post(_bot_api_url("createForumTopic"), json=payload)
                if resp.is_success:
                    data = resp.json()
                    thread_id = data["result"]["message_thread_id"]
                    tg_topic_repo.update_topic_id(user_id, topic.id, thread_id)
                    logger.info("tg_topic sync: created topic '{}' -> thread_id={}", topic.topic_name, thread_id)
                else:
                    logger.error("tg_topic sync: createForumTopic failed for '{}': {}", topic.topic_name, resp.text)
            except Exception as e:
                logger.exception("tg_topic sync: error creating topic '{}': {}", topic.topic_name, e)

    # Return refreshed list
    return tg_topic_repo.list_topics(user_id, group_id)
