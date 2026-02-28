"""Timezone conversion utilities for CLI display."""

import os
from datetime import datetime, timezone, timedelta


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


def local_to_utc(local_str: str) -> str:
    """Convert a local datetime string to UTC ISO 8601 with Z suffix.

    Accepts: 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DDTHH:MM', 'YYYY-MM-DD'.
    Already-UTC strings (ending with Z) are passed through.
    """
    if local_str.endswith("Z"):
        return local_str
    local_tz = _get_configured_tz()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(local_str, fmt)
            dt = dt.replace(tzinfo=local_tz)
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc_dt.microsecond // 1000:03d}Z"
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {local_str}")


def local_date_to_utc_range(date_str: str) -> tuple[str, str]:
    """Convert a local date (YYYY-MM-DD) to UTC start/end range covering the full local day."""
    local_tz = _get_configured_tz()
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=local_tz)
    day_end = day_start + timedelta(days=1)
    utc_start = day_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    utc_end = day_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return utc_start, utc_end
