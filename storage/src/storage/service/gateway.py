"""Host notification gateway. Preference picks WeChat or Telegram; the other is the fallback."""

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from storage.service import user_preference as user_pref_service
from storage.service import wechat as wechat_service
from storage.service.telegram import resolve_target
from storage.util import send_telegram_message_checked

CHANNEL_KEY = "notify_channel"
CHANNELS = ("wechat", "telegram")


@dataclass
class GatewayResult:
    ok: bool
    channel: Optional[str] = None
    fallback_from: Optional[str] = None
    preference: Optional[str] = None

    def __bool__(self):
        return self.ok

    def to_dict(self):
        return {
            "ok": self.ok,
            "channel": self.channel,
            "fallback_from": self.fallback_from,
            "preference": self.preference,
        }


def resolve_order(pref, availability):
    """Channels to try: preferred first, then the other, skipping unavailable ones.

    A missing availability flag is unavailable. An unknown preference means telegram.
    """
    preferred = pref if pref in CHANNELS else "telegram"
    other = "telegram" if preferred == "wechat" else "wechat"
    if isinstance(availability, dict):
        flags = {name: bool(availability.get(name)) for name in CHANNELS}
    else:
        present = set(availability or ())
        flags = {name: name in present for name in CHANNELS}
    return [name for name in (preferred, other) if flags[name]]


def _preference(user_id):
    row = user_pref_service.get_preference(user_id, CHANNEL_KEY)
    value = row.value if row else None
    return value if value in CHANNELS else "telegram"


def _stored_preference(user_id):
    row = user_pref_service.get_preference(user_id, CHANNEL_KEY)
    value = row.value if row else None
    return value if value in CHANNELS else None


def set_channel(user_id, channel):
    if channel == "default":
        user_pref_service.delete_preference(user_id, CHANNEL_KEY)
        return "telegram"
    if channel not in CHANNELS:
        raise ValueError("channel must be wechat, telegram, or default")
    user_pref_service.upsert_preference(user_id, CHANNEL_KEY, channel)
    return channel


def _wechat_available(user_id):
    return bool(wechat_service.notify_available(user_id))


def _telegram_available(user_id):
    return resolve_target(user_id) is not None


def _wechat_send(user_id, text):
    return bool(wechat_service.notify_user(user_id, text))


def _telegram_send(user_id, text):
    target = resolve_target(user_id)
    if not target:
        return False
    return bool(send_telegram_message_checked(target[0], target[1], text))


def _flag(hook, user_id):
    try:
        return bool(hook(user_id) if callable(hook) else hook)
    except Exception:
        logger.exception("gateway probe failed user_id={}", user_id)
        return False


def _deliver(hook, user_id, text):
    outcome = hook(user_id, text) if callable(hook) else hook
    return bool(outcome)


def status(user_id):
    pref = _preference(user_id)
    availability = {
        "wechat": _flag(_wechat_available, user_id),
        "telegram": _flag(_telegram_available, user_id),
    }
    return {
        "preference": pref,
        "stored": _stored_preference(user_id),
        "availability": availability,
        "order": resolve_order(pref, availability),
    }


def send(user_id, text) -> GatewayResult:
    if not isinstance(text, str) or not text.strip():
        return GatewayResult(False)
    try:
        pref = _preference(user_id)
    except Exception:
        logger.exception("gateway preference failed user_id={}", user_id)
        return GatewayResult(False)
    availability = {
        "wechat": _flag(_wechat_available, user_id),
        "telegram": _flag(_telegram_available, user_id),
    }
    order = resolve_order(pref, availability)
    for index, channel in enumerate(order):
        hook = _wechat_send if channel == "wechat" else _telegram_send
        try:
            ok = _deliver(hook, user_id, text)
        except Exception:
            logger.exception("gateway send failed user_id={} channel={}", user_id, channel)
            ok = False
        if not ok:
            continue
        fallback = order[0] if index else None
        if fallback:
            logger.warning(
                "gateway fallback user_id={} from={} to={}", user_id, fallback, channel,
            )
        return GatewayResult(True, channel=channel, fallback_from=fallback, preference=pref)
    return GatewayResult(False, preference=pref)
