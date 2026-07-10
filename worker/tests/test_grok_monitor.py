import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.entity.dto import Chat
from worker.monitor import (
    _apply_completion_metadata,
    _restart_grok_with_steer,
)


class GrokSteerTest(unittest.IsolatedAsyncioTestCase):
    async def test_steer_without_session_id_persists_error_message(self):
        with (
            patch("worker.monitor.message_callback") as message_callback,
            patch("worker.monitor.complete_process") as complete_process,
            patch("worker.monitor._mark_chat_stopped", new_callable=AsyncMock) as mark_stopped,
        ):
            await _restart_grok_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "backend_type": "grok_build"},
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

    async def test_steer_resumes_via_grok_resume_cmd(self):
        captured = {}

        async def fake_start(**kwargs):
            captured.update(kwargs)
            return "sess-1"

        bot_config = Mock()
        bot_config.name = "grok"
        bot_config.model = "grok-4.5"
        bot_config.api_key = "xai-secret"

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock(name="vm")),
            patch("agent.config.resolve_bot_config", return_value=bot_config),
            patch("agent.grok_build.start_detached_grok_ssh", side_effect=fake_start) as start,
            patch("worker.monitor.update_process_offset"),
            patch("worker.monitor.release_lease"),
        ):
            await _restart_grok_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "work_dir": "/repo", "backend_type": "grok_build"},
                {"status": "steer", "steer_text": "do more", "session_id": "sess-1"},
            )

        start.assert_awaited_once()
        self.assertEqual(
            captured["cmd"],
            ["grok", "--resume", "sess-1", "--output-format", "streaming-json", "--always-approve", "-m", "grok-4.5"],
        )
        self.assertEqual(captured["prompt"], "do more")
        self.assertEqual(captured["env"]["XAI_API_KEY"], "xai-secret")


class GrokApplyCompletionMetadataTest(unittest.IsolatedAsyncioTestCase):
    def _chat(self):
        return Chat(
            id="chat-1",
            create_time="",
            update_time="",
            messages=[],
            external_id="sid-old",
            work_dir="/repo",
        )

    async def test_applies_session_id_when_cwd_matches(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "completed", "session_id": "grok-1"},
            result_data=None,
            proc={"work_dir": "/repo"},
            backend_type="grok_build",
            chat_id="chat-1",
        )
        self.assertEqual(chat.external_id, "grok-1")

    async def test_skips_session_id_when_cwd_mismatch(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "completed", "session_id": "grok-1"},
            result_data=None,
            proc={"work_dir": "/other"},
            backend_type="grok_build",
            chat_id="chat-1",
        )
        self.assertEqual(chat.external_id, "sid-old")

    async def test_error_appends_message(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "error", "session_id": "grok-1"},
            result_data={"is_error": True, "result": "grok blew up"},
            proc={"work_dir": "/repo"},
            backend_type="grok_build",
            chat_id="chat-1",
        )
        self.assertEqual(chat.messages[-1].content, "grok blew up")


if __name__ == "__main__":
    unittest.main()
