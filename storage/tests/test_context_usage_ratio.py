import unittest

from storage.dto.chat import Chat


def _chat(**overrides) -> Chat:
    kwargs = dict(
        id="chat-1",
        create_time="2026-07-30T00:00:00Z",
        update_time="2026-07-30T00:00:00Z",
        messages=[],
    )
    kwargs.update(overrides)
    return Chat(**kwargs)


class ContextUsageRatioTest(unittest.TestCase):
    def test_none_context_window_returns_none(self):
        chat = _chat(context_window=None, input_tokens=100)
        self.assertIsNone(chat.context_usage_ratio())

    def test_zero_context_window_returns_none(self):
        chat = _chat(context_window=0, input_tokens=100)
        self.assertIsNone(chat.context_usage_ratio())

    def test_all_fields_set_returns_expected_ratio(self):
        chat = _chat(
            context_window=1000,
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=20,
        )
        self.assertEqual(chat.context_usage_ratio(), 0.2)

    def test_partially_none_token_fields_treated_as_zero(self):
        chat = _chat(
            context_window=1000,
            input_tokens=100,
            output_tokens=None,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        )
        self.assertEqual(chat.context_usage_ratio(), 0.1)


if __name__ == "__main__":
    unittest.main()
