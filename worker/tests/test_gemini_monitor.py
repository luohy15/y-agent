import unittest
from unittest.mock import AsyncMock, patch

from storage.entity.dto import Chat
from worker.monitor import _apply_claude_usage, _restart_gemini_with_steer, _sweep_orphan_running_chats


class GeminiMonitorTest(unittest.IsolatedAsyncioTestCase):
    async def test_steer_without_session_id_persists_error_message(self):
        with (
            patch("worker.monitor.message_callback") as message_callback,
            patch("worker.monitor.complete_process") as complete_process,
            patch("worker.monitor._mark_chat_stopped", new_callable=AsyncMock) as mark_stopped,
        ):
            await _restart_gemini_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "backend_type": "gemini_cli"},
                {
                    "status": "steer",
                    "steer_text": "new instructions",
                    "session_id": None,
                },
            )

        message_callback.assert_called_once()
        called_chat_id, msg = message_callback.call_args.args
        self.assertEqual(called_chat_id, "chat-1")
        self.assertEqual(msg.role, "assistant")
        self.assertIn("could not resume the steer message", msg.content)
        complete_process.assert_called_once_with("chat-1", status="error")
        mark_stopped.assert_awaited_once_with("chat-1")


class ClaudeUsageTest(unittest.TestCase):
    def _chat(self):
        return Chat(id="chat-1", create_time="", update_time="", messages=[])

    def test_dict_model_usage_skips_non_dict_entries(self):
        chat = self._chat()
        _apply_claude_usage(chat, {
            "num_turns": 2,
            "modelUsage": {
                "good": {
                    "inputTokens": 10,
                    "outputTokens": "6",
                    "cacheReadInputTokens": 4,
                    "cacheCreationInputTokens": 2,
                    "contextWindow": 200000,
                },
                "bad": "not-a-dict",
            },
        })
        self.assertEqual(chat.input_tokens, 5)
        self.assertEqual(chat.output_tokens, 3)
        self.assertEqual(chat.cache_read_input_tokens, 2)
        self.assertEqual(chat.cache_creation_input_tokens, 1)
        self.assertEqual(chat.context_window, 200000)

    def test_bad_model_usage_shapes_do_not_raise(self):
        for result_data in (
            {"modelUsage": "bad"},
            {"modelUsage": ["bad", {"inputTokens": object(), "contextWindow": "bad"}]},
            ["not-a-dict"],
            None,
        ):
            chat = self._chat()
            _apply_claude_usage(chat, result_data)


class OrphanSweepTest(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_marks_only_chats_without_process_rows(self):
        with (
            patch("worker.monitor.get_running_processes", return_value=[{"chat_id": "active"}]),
            patch("storage.repository.chat.find_running_chat_ids_older_than", return_value=["active", "orphan"]),
            patch("worker.monitor._mark_chat_stopped", new_callable=AsyncMock) as mark_stopped,
        ):
            await _sweep_orphan_running_chats()

        mark_stopped.assert_awaited_once_with("orphan")


if __name__ == "__main__":
    unittest.main()
