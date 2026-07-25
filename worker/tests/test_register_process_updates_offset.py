"""Regression tests for updates_offset preservation in register_process (todo 2885).

grok's `updates.jsonl` is cumulative for the life of a session, while
`register_process` rewrites the whole DynamoDB record on every turn. Dropping
`updates_offset` there made each new turn of a resumed session re-read the full
file from byte 0, the read that deadlocked chat aa346e's tail.
"""

import unittest
from unittest.mock import Mock, patch

from worker.process_manager import register_process


class RegisterProcessUpdatesOffsetTest(unittest.TestCase):
    def _register(self, stored: dict = None, session_id: str = "sess-1"):
        dynamodb = Mock()
        dynamodb.get_item.return_value = {"Item": stored} if stored else {}
        with patch("worker.process_manager._get_dynamodb", return_value=dynamodb):
            register_process(
                chat_id="aa346e", user_id=85, vm_name="default",
                session_id=session_id, backend_type="grok_build",
            )
        return dynamodb, dynamodb.put_item.call_args.kwargs["Item"]

    def test_same_session_carries_prior_updates_offset(self):
        dynamodb, item = self._register(
            {"session_id": {"S": "sess-1"}, "updates_offset": {"N": "3166223"}},
        )

        self.assertEqual(item["updates_offset"], {"N": "3166223"})
        self.assertEqual(item["session_id"], {"S": "sess-1"})
        # The stdout file is truncated per turn, so its offset still resets.
        self.assertEqual(item["stdout_offset"], {"N": "0"})
        self.assertEqual(item["status"], {"S": "running"})
        self.assertEqual(
            dynamodb.get_item.call_args.kwargs["Key"], {"id": {"S": "proc-aa346e"}},
        )

    def test_different_session_starts_at_zero(self):
        _, item = self._register(
            {"session_id": {"S": "sess-old"}, "updates_offset": {"N": "3166223"}},
        )

        self.assertNotIn("updates_offset", item)

    def test_prior_record_without_session_id_starts_at_zero(self):
        _, item = self._register({"updates_offset": {"N": "3166223"}})

        self.assertNotIn("updates_offset", item)

    def test_no_prior_record_starts_at_zero(self):
        _, item = self._register(None)

        self.assertNotIn("updates_offset", item)

    def test_same_session_without_prior_offset_starts_at_zero(self):
        _, item = self._register({"session_id": {"S": "sess-1"}})

        self.assertNotIn("updates_offset", item)

    def test_registration_without_session_id_skips_the_lookup(self):
        dynamodb, item = self._register(
            {"session_id": {"S": "sess-1"}, "updates_offset": {"N": "3166223"}},
            session_id=None,
        )

        dynamodb.get_item.assert_not_called()
        self.assertNotIn("updates_offset", item)
        self.assertNotIn("session_id", item)


if __name__ == "__main__":
    unittest.main()
