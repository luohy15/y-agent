import unittest
from types import SimpleNamespace
from unittest.mock import patch

import storage.service.telegram as tg


def _topic(group_id, topic_id):
    return SimpleNamespace(group_id=group_id, topic_id=topic_id)


def _user(telegram_id):
    return SimpleNamespace(telegram_id=telegram_id)


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        # Bot token is always present in these cases.
        p = patch.object(tg, "get_telegram_bot_token", return_value="tok")
        p.start()
        self.addCleanup(p.stop)

    def test_no_bot_token(self):
        with patch.object(tg, "get_telegram_bot_token", return_value=None):
            self.assertIsNone(tg.resolve_target(1, topic="dev"))

    def test_bound_topic(self):
        # (a) bound topic → (token, group_id, thread_id)
        with patch.object(tg, "find_topic_by_name", return_value=_topic(-100, 42)):
            self.assertEqual(tg.resolve_target(1, topic="dev"), ("tok", -100, 42))

    def test_unbound_topic_with_forum_group(self):
        # (b) no row for topic but user has a forum group → General (thread=None)
        with patch.object(tg, "find_topic_by_name", return_value=None), \
             patch.object(tg, "find_user_group_id", return_value=-100):
            self.assertEqual(tg.resolve_target(1, topic="dev"), ("tok", -100, None))

    def test_topic_row_present_but_topic_id_none(self):
        # (c) row exists but topic_id is None → use the row's group_id, General
        with patch.object(tg, "find_topic_by_name", return_value=_topic(-100, None)):
            self.assertEqual(tg.resolve_target(1, topic="dev"), ("tok", -100, None))

    def test_no_group_falls_back_to_dm(self):
        # (d) no forum group + DM available → DM
        with patch.object(tg, "find_topic_by_name", return_value=None), \
             patch.object(tg, "find_user_group_id", return_value=None), \
             patch.object(tg, "get_user_by_id", return_value=_user(555)):
            self.assertEqual(tg.resolve_target(1, topic="dev"), ("tok", 555, None))

    def test_no_group_no_dm_returns_none(self):
        # (e) no forum group + no telegram_id → None
        with patch.object(tg, "find_topic_by_name", return_value=None), \
             patch.object(tg, "find_user_group_id", return_value=None), \
             patch.object(tg, "get_user_by_id", return_value=_user(None)):
            self.assertIsNone(tg.resolve_target(1, topic="dev"))

    def test_manager_routes_to_dm(self):
        with patch.object(tg, "get_user_by_id", return_value=_user(555)):
            self.assertEqual(tg.resolve_target(1, topic="manager"), ("tok", 555, None))
            self.assertEqual(tg.resolve_target(1, topic=None), ("tok", 555, None))


if __name__ == "__main__":
    unittest.main()
