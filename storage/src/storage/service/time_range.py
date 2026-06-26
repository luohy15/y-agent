from __future__ import annotations

import datetime

from fava.util.date import parse_date


TIME_RANGE_ALIASES = {
    "ytd": "year to day",
    "mtd": "month to day",
    "qtd": "quarter to day",
    "wtd": "week to day",
    "today": "day",
    "1m": "day-30 to day-1",
    "3m": "day-90 to day-1",
    "1y": "day-365 to day-1",
    "all": "",
}


def parse_time_range(time_filter: str, default: str | None = None) -> tuple[datetime.date | None, datetime.date | None]:
    value = (time_filter or default or "").strip()
    value = TIME_RANGE_ALIASES.get(value.lower(), value)
    if not value:
        return None, None
    return parse_date(value)
