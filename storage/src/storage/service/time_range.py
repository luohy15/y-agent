from __future__ import annotations

import datetime

import fava.util.date as _fava_date
from fava.util.date import parse_date

from storage.util import local_today

# fava resolves relative tokens (day / week / month / ytd / mtd ...) against
# datetime.date.today(), i.e. the *process* timezone. Lambda and the VM both
# run UTC, so between 00:00 and 08:00 Asia/Shanghai "today" resolved to
# yesterday while the write path stamped rows in the configured zone (todo
# 2953). Rebind fava's day resolver to the configured-TZ local_today() once at
# import; substitute() looks the name up in module globals at call time, so
# this single rebind covers every relative token with no per-request patching.
if not hasattr(_fava_date, "local_today"):
    raise ImportError(
        "fava.util.date.local_today not found — fava's API changed; the "
        "configured-timezone rebind for time_range's relative date tokens "
        "(todo 2953) needs to be re-checked against the new fava version."
    )
_fava_date.local_today = local_today


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
