from __future__ import annotations

import datetime
import re

from storage.util import local_today

# Grammar adapted from fava 1.30.12 (fava/util/date.py), with an explicit
# today and the default December 31 fiscal year end only.
# Copyright (c) 2015-2016 Dominik Aumayr <dominik@aumayr.name>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

_RANGE_RE = re.compile(r"(.*?)(?:-|to)(?=\s*(?:fy)*\d{4})(.*)")
_VARIABLE_RE = re.compile(
    r"\(?(fiscal_year|year|fiscal_quarter|quarter"
    r"|month|week|day)(?:([-+])(\d+))?\)?"
)

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


def _substitute(value: str, today: datetime.date) -> str:
    for match in _VARIABLE_RE.finditer(value):
        complete, interval, sign, modifier = match.group(0, 1, 2, 3)
        offset = int(modifier or 0) * (1 if sign == "+" else -1)
        if interval in ("year", "fiscal_year"):
            replacement = str(today.year + offset)
            if interval == "fiscal_year":
                replacement = "fy" + replacement
        elif interval in ("quarter", "fiscal_quarter"):
            quarter = (today.month - 1) // 3 + offset
            year = today.year + quarter // 4
            replacement = f"{year}-q{quarter % 4 + 1}"
            if interval == "fiscal_quarter":
                # The original fiscal path validates the shifted date first.
                datetime.date(year, (quarter % 4) * 3 + 1, 1)
                replacement = "fy" + replacement
        elif interval == "month":
            year = today.year + (today.month + offset - 1) // 12
            month = (today.month + offset - 1) % 12 + 1
            replacement = f"{year}-{month:02}"
        elif interval == "week":
            replacement = (today + datetime.timedelta(weeks=offset)).strftime("%G-w%V")
        else:
            replacement = (today + datetime.timedelta(days=offset)).isoformat()
        value = value.replace(complete, replacement)
    return value


def _period_end(start: datetime.date, months: int = 0, days: int = 0) -> datetime.date:
    try:
        if months:
            year_delta, month = divmod(start.month - 1 + months, 12)
            return start.replace(year=start.year + year_delta, month=month + 1)
        return start + datetime.timedelta(days=days)
    except (ValueError, OverflowError):
        return datetime.date.max


def _parse_grammar(
    value: str, today: datetime.date,
) -> tuple[datetime.date | None, datetime.date | None]:
    """Parse the shared grammar to inclusive start and exclusive end dates."""
    value = _substitute(value.strip().lower(), today).lower()
    match = _RANGE_RE.match(value)
    if match:
        return _parse_grammar(match[1], today)[0], _parse_grammar(match[2], today)[1]

    if re.fullmatch(r"\d{4}", value):
        start = datetime.date(int(value), 1, 1)
        return start, _period_end(start, months=12)
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", value)
    if match:
        year, month = int(match[1]), int(match[2])
        start = datetime.date(year, month, int(match[3]) if match[3] else 1)
        return start, _period_end(start, days=1) if match[3] else _period_end(start, months=1)
    match = re.fullmatch(r"(\d{4})-w(\d{2})", value)
    if match:
        year, week = map(int, match.groups())
        start = datetime.datetime.strptime(f"{year}-W{week}-1", "%G-W%V-%w").date()
        return start, _period_end(start, days=7)
    match = re.fullmatch(r"(\d{4})-q([1234])", value)
    if match:
        year, quarter = map(int, match.groups())
        start = datetime.date(year, (quarter - 1) * 3 + 1, 1)
        return start, _period_end(start, months=3)
    match = re.fullmatch(r"fy(\d{4})(?:-q([1234]))?", value)
    if match:
        year = int(match[1])
        # Preserve fiscal boundary errors rather than clipping to date.max.
        start = datetime.date(year - 1, 12, 31) + datetime.timedelta(days=1)
        if not match[2]:
            return start, start.replace(year=year + 1)
        start = start.replace(month=(int(match[2]) - 1) * 3 + 1)
        end_year, end_month = divmod(start.month + 2, 12)
        return start, start.replace(year=year + end_year, month=end_month + 1)
    return None, None


def parse_time_range(
    time_filter: str, default: str | None = None, tz: str | None = None,
) -> tuple[datetime.date | None, datetime.date | None]:
    """`tz` (an IANA name, e.g. a client's browser timezone) overrides the
    configured Y_AGENT_TIMEZONE when resolving relative tokens ("today" /
    "month" / "ytd" / ...) against "now". Omitting `tz` preserves existing
    behavior byte-for-byte."""
    value = (time_filter or default or "").strip()
    value = TIME_RANGE_ALIASES.get(value.lower(), value)
    if not value:
        return None, None
    return _parse_grammar(value, local_today(tz))


def describe_time_range(
    time_filter: str | None,
    *,
    default: str | None = None,
    tz: str | None = None,
    effective: tuple[datetime.date | None, datetime.date | None] | None = None,
) -> dict:
    """Inclusive display bounds for a time-grammar input (todo 3580).

    Reuses `parse_time_range` (byte-identical parser). Returns
    `{input, recognized, from_date, to_date}` where the dates are inclusive
    ISO `YYYY-MM-DD` (`end_exclusive - 1 day`). `recognized` is false only
    when a non-empty input (after aliases) parses to nothing or raises;
    `all` / empty stay recognized with both bounds null. `effective` is an
    exclusive-end `(start, end)` pair that replaces the parsed window, for
    callers that substituted a fallback (finance history's trailing year).
    """
    raw = (time_filter or "").strip()
    value = (time_filter or default or "").strip()
    aliased = TIME_RANGE_ALIASES.get(value.lower(), value)

    recognized = True
    start: datetime.date | None = None
    end: datetime.date | None = None
    if aliased:
        try:
            start, end = parse_time_range(time_filter, default=default, tz=tz)
        except ValueError:
            recognized = False
            start, end = None, None
        else:
            if start is None and end is None:
                recognized = False

    if effective is not None:
        start, end = effective

    return {
        "input": raw,
        "recognized": recognized,
        "from_date": start.isoformat() if start else None,
        "to_date": (end - datetime.timedelta(days=1)).isoformat() if end else None,
    }
