import unittest

from storage.dto.chat import Chat, Message
from storage.service.chat import (
    CONTEXT_HANDOFF_THRESHOLD,
    HANDOFF_REMINDER_MARKER,
    maybe_append_handoff_reminder,
)


def _chat(messages=None, **overrides) -> Chat:
    kwargs = dict(
        id="chat-1",
        create_time="2026-07-30T00:00:00Z",
        update_time="2026-07-30T00:00:00Z",
        messages=messages or [],
    )
    kwargs.update(overrides)
    return Chat(**kwargs)


def _user_message(content: str, ts: int) -> Message:
    return Message(role="user", content=content, timestamp="2026-07-30T00:00:00Z", unix_timestamp=ts)


def _assistant_message(content: str, ts: int) -> Message:
    return Message(role="assistant", content=content, timestamp="2026-07-30T00:00:00Z", unix_timestamp=ts)


def _over_threshold_chat(messages=None) -> Chat:
    return _chat(
        messages=messages,
        context_window=1000,
        input_tokens=300,  # ratio 0.3 > 0.20 threshold
    )


class MaybeAppendHandoffReminderTest(unittest.TestCase):
    def test_no_usage_leaves_content_unchanged(self):
        chat = _chat(context_window=None)
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_under_threshold_leaves_content_unchanged(self):
        chat = _chat(context_window=1000, input_tokens=100)  # ratio 0.1
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_exactly_at_threshold_leaves_content_unchanged(self):
        chat = _chat(context_window=1000, input_tokens=int(1000 * CONTEXT_HANDOFF_THRESHOLD))
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_over_threshold_appends_marker(self):
        chat = _over_threshold_chat()
        result = maybe_append_handoff_reminder(chat, "hello")
        self.assertTrue(result.startswith("hello\n\n"))
        self.assertIn(HANDOFF_REMINDER_MARKER, result)

    def test_marker_already_in_trailing_batch_skips(self):
        chat = _over_threshold_chat(messages=[
            _user_message(f"earlier msg {HANDOFF_REMINDER_MARKER} some reminder", 1),
        ])
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_marker_before_assistant_message_refires(self):
        chat = _over_threshold_chat(messages=[
            _user_message(f"earlier msg {HANDOFF_REMINDER_MARKER} some reminder", 1),
            _assistant_message("ack", 2),
        ])
        result = maybe_append_handoff_reminder(chat, "hello")
        self.assertTrue(result.startswith("hello\n\n"))
        self.assertIn(HANDOFF_REMINDER_MARKER, result)


if __name__ == "__main__":
    unittest.main()
