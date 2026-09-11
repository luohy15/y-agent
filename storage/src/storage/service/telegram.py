"""Telegram routing service — resolve a Telegram DM target for a user."""

from typing import Optional, Tuple

from loguru import logger

from storage.repository.user import get_user_by_id
from storage.util import get_telegram_bot_token, send_telegram_message_checked


def resolve_target(user_id: int, topic: Optional[str] = None) -> Optional[Tuple[str, int]]:
    """Resolve a Telegram delivery target for a user.

    Only topic in (None, '', 'manager') resolves, to the user's DM via
    user.telegram_id. Any other topic name is rejected outright — the
    Telegram group is retired, so a non-manager topic never falls through to
    DM; it simply has no Telegram delivery.

    Returns (bot_token, tg_chat_id) or None if no valid target.
    """
    bot_token = get_telegram_bot_token()
    if not bot_token:
        return None

    if topic and topic != 'manager':
        logger.debug("telegram: topic '{}' is not eligible for Telegram delivery", topic)
        return None

    user = get_user_by_id(user_id)
    if not user or not user.telegram_id:
        logger.debug("telegram: no telegram_id for user_id={}", user_id)
        return None
    return (bot_token, user.telegram_id)


def send_owner_notice(user_id: int, text: str) -> bool:
    """Best-effort DM to the owner. Never raises."""
    try:
        target = resolve_target(user_id)
        if not target:
            return False
        return bool(send_telegram_message_checked(target[0], target[1], text))
    except Exception:
        logger.exception("telegram: owner notice failed for user_id={}", user_id)
        return False
