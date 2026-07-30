"""On-VM scrape cache (todo 2872 sub-task 3): ~240s TTL, atomic 0600
replace, and a cache hit must return the item untouched (never restamp
`observed_at`, or the freshness computation downstream would lie about how
old the reading actually is)."""

import os
import tempfile
import unittest
from unittest.mock import patch

from yagent.commands.usage import _cache


class ClaudeUsageCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = patch.dict(os.environ, {"Y_AGENT_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_miss_when_no_file(self):
        self.assertIsNone(_cache.read(now_ts=1000.0))

    def test_hit_within_ttl_returns_the_original_item_unmodified(self):
        item = {"observed_at": "2026-07-30T00:00:00Z", "availability": "available"}
        _cache.write(item, now_ts=1000.0)

        cached = _cache.read(now_ts=1000.0 + _cache.TTL_SECONDS - 1)
        self.assertEqual(cached, item)
        # Never restamped: the cached item's own observed_at is untouched.
        self.assertEqual(cached["observed_at"], "2026-07-30T00:00:00Z")

    def test_miss_once_ttl_elapsed(self):
        item = {"observed_at": "2026-07-30T00:00:00Z"}
        _cache.write(item, now_ts=1000.0)

        self.assertIsNone(_cache.read(now_ts=1000.0 + _cache.TTL_SECONDS + 1))

    def test_file_is_mode_0600(self):
        _cache.write({"a": 1}, now_ts=1000.0)
        mode = oct(os.stat(_cache.cache_path()).st_mode)[-3:]
        self.assertEqual(mode, "600")

    def test_corrupt_cache_file_is_a_miss_not_an_error(self):
        path = _cache.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")

        self.assertIsNone(_cache.read(now_ts=1000.0))


if __name__ == "__main__":
    unittest.main()
