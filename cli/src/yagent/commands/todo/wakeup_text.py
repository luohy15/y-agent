"""Shared CLI wording for an active todo's nearest outstanding wakeup (todo 3793).

The timestamp is display-only. It is not the todo due date, and it does not
say the trace is only waiting. Overdue means the receipt is past due and still
pending or accepted; the watchdog grace window is not applied here.
"""
from datetime import datetime, timezone
from typing import Optional

from yagent.time_util import _get_configured_tz


def wakeup_label(todo: dict, now_ms: Optional[int] = None) -> Optional[str]:
    if todo.get("status") != "active":
        return None
    ms = todo.get("next_wakeup_at_unix")
    if type(ms) is not int:
        return None
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(_get_configured_tz())
    stamp = when.strftime("%Y-%m-%d %H:%M")
    if ms < now_ms:
        return f"Wakeup overdue · {stamp}"
    return f"Wakeup scheduled · {stamp}"
