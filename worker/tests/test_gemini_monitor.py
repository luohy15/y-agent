import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.entity.dto import Chat
from worker.monitor import (
    _apply_claude_usage,
    _apply_completion_metadata,
    _restart_gemini_with_steer,
    _sweep_orphan_running_chats,
    _tail_and_process,
)


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


class MonitorResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_pause_preserves_existing_session_id(self):
        result = {
            "offset": 123,
            "last_message_id": "msg-2",
            "session_id": None,
            "is_done": False,
            "result_data": None,
            "status": "monitoring",
            "consumed_steer_ids": [],
        }

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock()),
            patch("storage.service.chat.get_chat_by_id", new_callable=AsyncMock) as get_chat,
            patch("worker.runner.make_steer_checker", return_value=lambda: []),
            patch("agent.claude_code.tail_ssh_output", new_callable=AsyncMock, return_value=result),
            patch("worker.monitor.update_process_offset") as update_offset,
            patch("worker.monitor.release_lease") as release_lease,
        ):
            get_chat.return_value = Chat(id="chat-1", create_time="", update_time="", messages=[])
            await _tail_and_process(
                "chat-1",
                {
                    "user_id": 1,
                    "vm_name": "vm",
                    "backend_type": "claude_code",
                    "session_id": "session-existing",
                },
                "lambda-1",
                deadline_at=0,
            )

        self.assertEqual(update_offset.call_args.kwargs["session_id"], "session-existing")
        release_lease.assert_called_once_with("chat-1")


class ApplyCompletionMetadataResumeTest(unittest.IsolatedAsyncioTestCase):
    def _chat(self):
        return Chat(
            id="chat-1",
            create_time="",
            update_time="",
            messages=[],
            external_id="sid-old",
            work_dir="/repo",
        )

    async def _apply(self, backend_type, result, proc=None, result_data=None):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result=result,
            result_data=result_data,
            proc={"work_dir": "/repo", **(proc or {})},
            backend_type=backend_type,
            chat_id="chat-1",
        )
        return chat

    async def test_apply_completion_metadata_claude_falls_back_to_proc_session_id_on_error(self):
        chat = await self._apply(
            "claude_code",
            {"status": "error", "session_id": None},
            proc={"session_id": "sid-from-ddb"},
            result_data={"is_error": True, "result": "failed"},
        )

        self.assertEqual(chat.external_id, "sid-from-ddb")

    async def test_apply_completion_metadata_claude_prefers_result_session_id_over_proc(self):
        chat = await self._apply(
            "claude_code",
            {"status": "completed", "session_id": "sid-from-result"},
            proc={"session_id": "sid-from-ddb"},
        )

        self.assertEqual(chat.external_id, "sid-from-result")

    async def test_apply_completion_metadata_skips_when_cwd_mismatch_even_with_fallback(self):
        chat = self._chat()
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": "completed", "session_id": None},
            result_data=None,
            proc={"work_dir": "/other", "session_id": "sid-from-ddb"},
            backend_type="claude_code",
            chat_id="chat-1",
        )

        self.assertEqual(chat.external_id, "sid-old")

    async def test_apply_completion_metadata_codex_falls_back_to_proc_session_id(self):
        chat = await self._apply(
            "codex",
            {"status": "completed", "thread_id": None},
            proc={"session_id": "thread-from-ddb"},
        )

        self.assertEqual(chat.external_id, "thread-from-ddb")

    async def test_apply_completion_metadata_gemini_falls_back_to_proc_session_id(self):
        chat = await self._apply(
            "gemini_cli",
            {"status": "completed", "session_id": None},
            proc={"session_id": "gemini-from-ddb"},
        )

        self.assertEqual(chat.external_id, "gemini-from-ddb")


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
