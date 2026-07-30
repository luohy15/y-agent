"""Tests for storage.util.local_today() — the single source of "today" shared
by the model-usage write path and the time_range read path (todo 2953). Run
under TZ=UTC so the fix is actually exercised: without the configured-TZ
binding, local_today() would silently fall back to the process (UTC) date.
"""

import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from storage.util import local_today


class LocalTodayTest(unittest.TestCase):
    def test_resolves_in_configured_timezone_not_process_timezone(self):
        with patch.dict(os.environ, {"Y_AGENT_TIMEZONE": "Pacific/Kiritimati"}):
            expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
            self.assertEqual(local_today(), expected)


if __name__ == "__main__":
    unittest.main()
