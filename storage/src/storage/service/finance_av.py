"""Shared Alpha Vantage helpers used by the realtime / fundamentals / price-series services."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# Alpha Vantage returns naïve timestamps in US Eastern (EDT/EST per DST).
AV_TZ = ZoneInfo("America/New_York")


def av_aware_utc(value: datetime) -> datetime:
    """Convert an AV timestamp to aware UTC. Naïve values are assumed US/Eastern."""
    if value.tzinfo is None:
        return value.replace(tzinfo=AV_TZ).astimezone(UTC)
    return value.astimezone(UTC)
