import unittest
from unittest.mock import AsyncMock, patch

from worker.monitor import _restart_gemini_with_steer


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


if __name__ == "__main__":
    unittest.main()
