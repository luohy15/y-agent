import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.entity.dto import Chat
from worker.monitor import (
    _apply_completion_metadata,
    _restart_pi_with_steer,
    _tail_and_process,
)


class PiSteerTest(unittest.IsolatedAsyncioTestCase):
    async def test_steer_without_session_id_persists_error_message(self):
        with (
            patch("worker.monitor.message_callback") as message_callback,
            patch("worker.monitor.complete_process") as complete_process,
            patch("worker.monitor._mark_chat_stopped", new_callable=AsyncMock) as mark_stopped,
        ):
            await _restart_pi_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "backend_type": "pi_cli"},
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

    async def test_steer_resumes_via_pi_session_cmd(self):
        captured = {}

        async def fake_start(**kwargs):
            captured.update(kwargs)
            return "sess-1"

        bot_config = Mock()
        bot_config.model = "google/gemini-2.5-flash"
        bot_config.api_key = "secret"

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock(name="vm")),
            patch("agent.config.resolve_bot_config", return_value=bot_config),
            patch("agent.pi_cli.start_detached_pi_ssh", side_effect=fake_start) as start,
            patch("worker.monitor.update_process_offset"),
            patch("worker.monitor.release_lease"),
        ):
            await _restart_pi_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "work_dir": "/repo", "backend_type": "pi_cli"},
                {"status": "steer", "steer_text": "do more", "session_id": "sess-1"},
            )

        start.assert_awaited_once()
        self.assertEqual(
            captured["cmd"],
            ["pi", "-p", "--mode", "json", "--session", "sess-1",
             "--model", "google/gemini-2.5-flash", "--api-key", "secret"],
        )
        self.assertEqual(captured["prompt"], "do more")


class PiMonitorResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_pi_tail_persists_latest_offset(self):
        result = {
            "offset": 456,
            "last_message_id": "msg-456",
            "session_id": "pi-456",
            "is_done": False,
            "result_data": None,
            "status": "monitoring",
            "consumed_steer_ids": ["steer-1"],
        }

        async def cancellable_tail(**kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return result

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock()),
            patch("storage.service.chat.get_chat_by_id", new_callable=AsyncMock) as get_chat,
            patch("worker.runner.make_steer_checker", return_value=lambda: []),
            patch("agent.pi_cli.tail_pi_output", side_effect=cancellable_tail),
            patch("worker.monitor.update_process_offset") as update_offset,
            patch("worker.monitor.release_lease") as release_lease,
        ):
            get_chat.return_value = Chat(id="chat-1", create_time="", update_time="", messages=[])
            task = asyncio.create_task(_tail_and_process(
                "chat-1",
                {
                    "user_id": 1,
                    "vm_name": "vm",
                    "backend_type": "pi_cli",
                    "session_id": "session-existing",
                },
                "lambda-1",
                deadline_at=0,
            ))
            await asyncio.sleep(0)
            task.cancel()
            await task

        self.assertEqual(update_offset.call_args.kwargs["offset"], 456)
        self.assertEqual(update_offset.call_args.kwargs["last_message_id"], "msg-456")
        self.assertEqual(update_offset.call_args.kwargs["session_id"], "pi-456")
        self.assertEqual(update_offset.call_args.kwargs["consumed_steer_ids"], ["steer-1"])
        release_lease.assert_called_once_with("chat-1")


class PiApplyCompletionMetadataTest(unittest.IsolatedAsyncioTestCase):
    def _chat(self):
        return Chat(
            id="chat-1",
            create_time="",
            update_time="",
            messages=[],
            external_id="sid-old",
            work_dir="/repo",
        )

    async def test_falls_back_to_proc_session_id(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "completed", "session_id": None},
            result_data=None,
            proc={"work_dir": "/repo", "session_id": "pi-from-ddb"},
            backend_type="pi_cli",
            chat_id="chat-1",
        )
        self.assertEqual(chat.external_id, "pi-from-ddb")

    async def test_applies_usage(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "completed", "session_id": "pi-1"},
            result_data={"is_error": False, "usage": {"input_tokens": 30, "output_tokens": 9}},
            proc={"work_dir": "/repo"},
            backend_type="pi_cli",
            chat_id="chat-1",
        )
        self.assertEqual(chat.external_id, "pi-1")
        self.assertEqual(chat.input_tokens, 30)
        self.assertEqual(chat.output_tokens, 9)

    async def test_error_appends_message(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "error", "session_id": "pi-1"},
            result_data={"is_error": True, "result": "pi blew up"},
            proc={"work_dir": "/repo"},
            backend_type="pi_cli",
            chat_id="chat-1",
        )
        self.assertEqual(chat.messages[-1].content, "pi blew up")


if __name__ == "__main__":
    unittest.main()
