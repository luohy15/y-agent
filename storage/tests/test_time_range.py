"""Table-driven tests for storage.service.time_range.parse_time_range — the
shared finance/usage time grammar (fava date parsing + a small alias table).

Covers the exclusive-fava-end boundary the usage API PRD flags as a real
off-by-one source: callers converting to inclusive `<=` semantics must
subtract one day from the returned end.

Also covers todo 2953: relative tokens (today/ytd/mtd/day/...) must resolve
against Y_AGENT_TIMEZONE, not the process timezone, which is why every
assertion below uses storage.util.local_today() rather than
datetime.date.today() and two of them pin Y_AGENT_TIMEZONE to a zone whose
current date differs from the process's.
"""

import datetime
import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import fava.util.date as _fava_date
import storage.service.time_range as time_range
from storage.service.time_range import parse_time_range
from storage.util import local_today


class ParseTimeRangeTest(unittest.TestCase):
    def test_bare_year_resolves_to_calendar_year_exclusive_end(self):
        start, end = parse_time_range("2024")
        self.assertEqual(start, datetime.date(2024, 1, 1))
        self.assertEqual(end, datetime.date(2025, 1, 1))

    def test_year_month_resolves_to_that_month_exclusive_end(self):
        start, end = parse_time_range("2024-05")
        self.assertEqual(start, datetime.date(2024, 5, 1))
        self.assertEqual(end, datetime.date(2024, 6, 1))

    def test_year_quarter_resolves_to_that_quarter_exclusive_end(self):
        start, end = parse_time_range("2024-q2")
        self.assertEqual(start, datetime.date(2024, 4, 1))
        self.assertEqual(end, datetime.date(2024, 7, 1))

    def test_specific_date_resolves_to_single_day_exclusive_end(self):
        start, end = parse_time_range("2024-05-15")
        self.assertEqual(start, datetime.date(2024, 5, 15))
        self.assertEqual(end, datetime.date(2024, 5, 16))

    def test_explicit_range_resolves_to_given_bounds(self):
        # fava's "X to Y" end is Y's own exclusive end (Y+1 day when Y is a
        # single date), matching the day-N to day pattern used elsewhere.
        start, end = parse_time_range("2024-05-01 to 2024-05-10")
        self.assertEqual(start, datetime.date(2024, 5, 1))
        self.assertEqual(end, datetime.date(2024, 5, 11))

    def test_all_alias_is_unbounded(self):
        self.assertEqual(parse_time_range("all"), (None, None))

    def test_empty_input_is_unbounded(self):
        self.assertEqual(parse_time_range(""), (None, None))
        self.assertEqual(parse_time_range(None), (None, None))

    def test_ytd_alias_resolves_to_year_to_day(self):
        today = local_today()
        start, end = parse_time_range("ytd")
        self.assertEqual(start, datetime.date(today.year, 1, 1))
        # "year to day" is inclusive of today via fava's day-grammar, which
        # itself returns an exclusive end one day past today.
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_today_alias_resolves_to_single_day_matching_day_alias(self):
        today_result = parse_time_range("today")
        day_result = parse_time_range("day")
        self.assertEqual(today_result, day_result)
        start, end = today_result
        today = local_today()
        self.assertEqual(start, today)
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_day_alias_resolved_via_fava_directly(self):
        start, end = parse_time_range("day")
        today = local_today()
        self.assertEqual(start, today)
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_exclusive_end_to_inclusive_conversion(self):
        """Mirrors the API layer's `end - timedelta(days=1)` conversion the
        PRD says caught a real off-by-one: a quarter's inclusive last day is
        one day before the exclusive end fava returns."""
        _, end = parse_time_range("2024-q2")
        inclusive_to_date = end - datetime.timedelta(days=1)
        self.assertEqual(inclusive_to_date, datetime.date(2024, 6, 30))

    def test_default_used_when_time_filter_blank(self):
        start, end = parse_time_range("", default="2024-05")
        self.assertEqual(start, datetime.date(2024, 5, 1))
        self.assertEqual(end, datetime.date(2024, 6, 1))

    def test_explicit_filter_takes_precedence_over_default(self):
        start, end = parse_time_range("2024-01", default="2024-05")
        self.assertEqual(start, datetime.date(2024, 1, 1))
        self.assertEqual(end, datetime.date(2024, 2, 1))

    def test_today_resolves_in_configured_timezone_east_of_utc(self):
        # Pacific/Kiritimati is UTC+14; its local date runs ahead of the
        # process (UTC) date roughly 10:00-24:00 UTC. This fails on the
        # pre-fix code (fava's local_today() = process date.today()).
        with patch.dict(os.environ, {"Y_AGENT_TIMEZONE": "Pacific/Kiritimati"}):
            expected = datetime.datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
            start, _ = parse_time_range("today")
        self.assertEqual(start, expected)

    def test_today_resolves_in_configured_timezone_west_of_utc(self):
        # Etc/GMT+12 is UTC-12; its local date trails the process (UTC) date
        # roughly 00:00-12:00 UTC. Combined with the east-of-UTC case above,
        # this pair fails on the pre-fix code at any hour of the day, not
        # only during the reported 00:00-08:00 Asia/Shanghai window.
        with patch.dict(os.environ, {"Y_AGENT_TIMEZONE": "Etc/GMT+12"}):
            expected = datetime.datetime.now(ZoneInfo("Etc/GMT+12")).date()
            start, _ = parse_time_range("today")
        self.assertEqual(start, expected)


class FavaLocalTodayBindingTest(unittest.TestCase):
    def test_fava_local_today_is_rebound_to_our_helper(self):
        self.assertIs(_fava_date.local_today, local_today)
        self.assertIs(_fava_date.local_today, time_range.local_today)


if __name__ == "__main__":
    unittest.main()
