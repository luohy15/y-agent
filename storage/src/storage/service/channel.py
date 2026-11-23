"""Owner-scoped binding inventory for the Gateway module."""

from storage.service import telegram, wechat
from storage.service.gateway import status as _notify
from storage.service.telegram import channel_state as _telegram_state
from storage.service.wechat import ChannelError as ChannelError, channel_summary as _wechat_state

CHANNELS = ("telegram", "wechat")


def health(channel, status, available):
    if channel not in CHANNELS:
        raise ValueError("Unknown channel")
    if status in {"unsupported", "unbound", "pending", "revoked"}:
        return status
    if status == "active":
        return "ok" if available else ("stale" if channel == "wechat" else "unavailable")
    return "unavailable"


def list_channels(user_id):
    notify = _notify(user_id)
    telegram_state = _telegram_state(user_id)
    try:
        wechat_state = _wechat_state(user_id)
    except ChannelError as exc:
        if exc.status != 403:
            raise
        wechat_state = {"status": "unsupported"}

    channels = []
    for name, state in zip(CHANNELS, (telegram_state, wechat_state), strict=True):
        status = state["status"]
        available = notify["availability"][name]
        row = dict(channel=name, status=status, supported=status != "unsupported",
                   bound=status == "active", health=health(name, status, available),
                   peer=state.get("peer"), available=available)
        if name == "telegram":
            row["token_configured"] = state["token_configured"]
        else:
            for key in ("account", "heartbeat_age_seconds", "last_poll_age_seconds", "last_error"):
                row[key] = state.get(key)
            row["outbox"] = state.get("outbox", {})
        channels.append(row)
    return {"channels": channels, "notify": notify}


def unbind(user_id, channel):
    if channel == "telegram":
        telegram.unbind_owner(user_id)
    elif channel == "wechat":
        wechat.owner_state(user_id, "unbind")
    else:
        raise ValueError("Unknown channel")
    return list_channels(user_id)
