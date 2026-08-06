"""Unit tests for api.controller.trace.get_latest_chat.

Covers the dev-topic preference added for todo 3070: the endpoint must agree
with the right drawer's own default pick (modules/chat/ui/panel.tsx's dev
pin, which queries topic=dev for the trace), not independently pick the
newest chat by updated_at.

DB is mocked; nothing touches a real database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.controller import trace as trace_controller
from storage.repository.chat import ChatSummary


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _summary(chat_id, topic=""):
    return ChatSummary(
        chat_id=chat_id,
        title="",
        created_at="2026-08-07T00:00:00Z",
        updated_at="2026-08-07T00:00:00Z",
        topic=topic,
        skill="",
        routine_id="",
        backend="claude_code",
        bot_name="",
        created_at_unix=0,
        updated_at_unix=0,
        status="idle",
        unread=False,
    )


class GetLatestChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_chats_returns_none(self):
        with patch.object(trace_controller, "find_chats_by_trace_id", return_value=[]):
            result = await trace_controller.get_latest_chat(_request(), trace_id="3070")
        self.assertEqual(result, {"chat_id": None})

    async def test_prefers_dev_topic_chat_over_newest(self):
        # Newest-first order (as the repo returns), with the dev chat not first.
        chats = [_summary("review-leaf", topic="review"), _summary("impl-leaf", topic="impl"), _summary("dev-coord", topic="dev")]
        with patch.object(trace_controller, "find_chats_by_trace_id", return_value=chats):
            result = await trace_controller.get_latest_chat(_request(), trace_id="3070")
        self.assertEqual(result, {"chat_id": "dev-coord"})

    async def test_falls_back_to_newest_when_no_dev_chat(self):
        chats = [_summary("review-leaf", topic="review"), _summary("impl-leaf", topic="impl")]
        with patch.object(trace_controller, "find_chats_by_trace_id", return_value=chats):
            result = await trace_controller.get_latest_chat(_request(), trace_id="3070")
        self.assertEqual(result, {"chat_id": "review-leaf"})


if __name__ == "__main__":
    unittest.main()
