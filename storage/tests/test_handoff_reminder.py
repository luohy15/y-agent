import unittest

from storage.dto.chat import Chat, Message
from storage.service.chat import (
    CONTEXT_HANDOFF_ABSOLUTE_TOKENS,
    CONTEXT_HANDOFF_RATIO,
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
    # 200k window: threshold is min(0.5 * 200_000, 200_000) = 100_000 tokens.
    return _chat(
        messages=messages,
        context_window=200_000,
        input_tokens=150_000,  # 150_000 > 100_000 threshold
    )


class MaybeAppendHandoffReminderTest(unittest.TestCase):
    def test_no_usage_leaves_content_unchanged(self):
        chat = _chat(context_window=None)
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_under_threshold_leaves_content_unchanged(self):
        chat = _chat(context_window=200_000, input_tokens=50_000)  # < 100_000 threshold
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_exactly_at_threshold_leaves_content_unchanged(self):
        threshold = int(200_000 * CONTEXT_HANDOFF_RATIO)
        chat = _chat(context_window=200_000, input_tokens=threshold)
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

    def test_200k_window_does_not_fire_at_45_percent(self):
        chat = _chat(context_window=200_000, input_tokens=90_000)  # 45% < 50% threshold
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")

    def test_200k_window_fires_at_55_percent(self):
        chat = _chat(context_window=200_000, input_tokens=110_000)  # 55% > 50% threshold
        result = maybe_append_handoff_reminder(chat, "hello")
        self.assertIn(HANDOFF_REMINDER_MARKER, result)

    def test_1m_window_fires_at_21_percent_above_absolute_cap(self):
        # 1M window: threshold is min(0.5 * 1_000_000, 200_000) = 200_000 tokens.
        chat = _chat(context_window=1_000_000, input_tokens=210_000)  # 21% > 200_000 cap
        self.assertGreater(210_000, CONTEXT_HANDOFF_ABSOLUTE_TOKENS)
        result = maybe_append_handoff_reminder(chat, "hello")
        self.assertIn(HANDOFF_REMINDER_MARKER, result)

    def test_1m_window_does_not_fire_at_19_percent(self):
        chat = _chat(context_window=1_000_000, input_tokens=190_000)  # 19% < 200_000 cap
        self.assertEqual(maybe_append_handoff_reminder(chat, "hello"), "hello")


if __name__ == "__main__":
    unittest.main()
