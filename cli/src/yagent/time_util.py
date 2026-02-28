"""Timezone conversion utilities for CLI display."""

import os
from datetime import datetime


def _get_configured_tz():
    """Return the configured timezone, falling back to system local."""
    from dateutil import tz as dateutil_tz
    tz_name = os.getenv("Y_AGENT_TIMEZONE")
    if tz_name:
        tz = dateutil_tz.gettz(tz_name)
        if tz:
            return tz
    return dateutil_tz.tzlocal()


def utc_to_local(utc_str: str) -> str:
    """Convert UTC ISO 8601 string to local datetime string."""
    utc_str_clean = utc_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(utc_str_clean)
    local_dt = dt.astimezone(_get_configured_tz())
    return local_dt.strftime("%Y-%m-%d %H:%M")
