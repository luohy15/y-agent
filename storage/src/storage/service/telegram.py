"""Telegram routing service — resolve a Telegram target (DM or forum topic) for a user."""

from typing import Optional, Tuple

from loguru import logger

from storage.repository.tg_topic import find_topic_by_name
from storage.repository.user import get_user_by_id
from storage.util import get_telegram_bot_token


def resolve_target(user_id: int, topic: Optional[str] = None) -> Optional[Tuple[str, int, Optional[int]]]:
    """Resolve a Telegram delivery target for a user.

    - topic in (None, '', 'manager') routes to the user's DM via user.telegram_id.
    - Any other topic name requires a tg_topic binding for the user.

    Returns (bot_token, tg_chat_id, message_thread_id) or None if no valid target.
    """
    bot_token = get_telegram_bot_token()
    if not bot_token:
        return None

    if topic and topic != 'manager':
        tg_topic = find_topic_by_name(user_id, topic)
        if not tg_topic or tg_topic.topic_id is None:
            logger.debug("telegram: no tg_topic binding for topic '{}', skip", topic)
            return None
        return (bot_token, tg_topic.group_id, tg_topic.topic_id)

    user = get_user_by_id(user_id)
    if not user or not user.telegram_id:
        logger.debug("telegram: no telegram_id for user_id={}", user_id)
        return None
    return (bot_token, user.telegram_id, None)
