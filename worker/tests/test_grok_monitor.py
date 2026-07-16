import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.entity.dto import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.monitor import (
    _apply_completion_metadata,
    _collect_tool_call_ids,
    _collect_tool_result_ids,
    _restart_grok_with_steer,
    _tail_and_process,
)


def _msg(role: str, tool_calls=None, tool_call_id=None, msg_id="m1") -> Message:
    return Message(
        id=msg_id,
        role=role,
        content="",
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
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
        bot_config.base_url = None

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
        self.assertIs(captured["bot_config"], bot_config)

    async def test_steer_restart_preserves_updates_jsonl_offset(self):
        # updates.jsonl lives in the same session dir across a steer restart
        # (only the stdout file resets), so its byte offset must carry
        # forward rather than reset to 0 like the stdout offset does.
        bot_config = Mock()
        bot_config.name = "grok"
        bot_config.model = "grok-4.5"
        bot_config.api_key = "xai-secret"
        bot_config.base_url = None

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock(name="vm")),
            patch("agent.config.resolve_bot_config", return_value=bot_config),
            patch("agent.grok_build.start_detached_grok_ssh", new_callable=AsyncMock, return_value="sess-1"),
            patch("worker.monitor.update_process_offset") as update_offset,
            patch("worker.monitor.release_lease"),
        ):
            await _restart_grok_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "work_dir": "/repo", "backend_type": "grok_build"},
                {"status": "steer", "steer_text": "do more", "session_id": "sess-1", "updates_offset": 4096},
            )

        self.assertEqual(update_offset.call_args.kwargs["offset"], 0)
        self.assertEqual(update_offset.call_args.kwargs["updates_offset"], 4096)


class CollectToolCallIdsTest(unittest.TestCase):
    def test_collects_ids_from_assistant_tool_calls_only(self):
        messages = [
            _msg("user", msg_id="m1"),
            _msg("assistant", tool_calls=[{"id": "tc-1"}, {"id": "tc-2"}], msg_id="m2"),
            _msg("tool", tool_call_id="tc-1", msg_id="m3"),
            _msg("assistant", tool_calls=None, msg_id="m4"),
        ]
        self.assertEqual(_collect_tool_call_ids(messages), {"tc-1", "tc-2"})

    def test_empty_history_yields_empty_set(self):
        self.assertEqual(_collect_tool_call_ids([]), set())


class CollectToolResultIdsTest(unittest.TestCase):
    def test_collects_ids_from_tool_role_messages_only(self):
        messages = [
            _msg("user", msg_id="m1"),
            _msg("assistant", tool_calls=[{"id": "tc-1"}], msg_id="m2"),
            _msg("tool", tool_call_id="tc-1", msg_id="m3"),
            _msg("tool", tool_call_id="tc-2", msg_id="m4"),
            _msg("tool", tool_call_id=None, msg_id="m5"),
        ]
        self.assertEqual(_collect_tool_result_ids(messages), {"tc-1", "tc-2"})

    def test_empty_history_yields_empty_set(self):
        self.assertEqual(_collect_tool_result_ids([]), set())


class GrokTailDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_tail_passes_work_dir_session_and_updates_offset(self):
        captured = {}

        async def fake_tail(**kwargs):
            captured.update(kwargs)
            return {
                "offset": 10,
                "last_message_id": "m2",
                "session_id": "sess-1",
                "updates_offset": 512,
                "is_done": False,
                "result_data": None,
                "status": "monitoring",
                "consumed_steer_ids": [],
            }

        chat = Chat(
            id="chat-1", create_time="", update_time="", messages=[
                _msg("assistant", tool_calls=[{"id": "tc-prior"}], msg_id="m1"),
                _msg("tool", tool_call_id="tc-prior", msg_id="m2"),
            ],
        )

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock()),
            patch("storage.service.chat.get_chat_by_id", new_callable=AsyncMock, return_value=chat),
            patch("worker.runner.make_steer_checker", return_value=lambda: []),
            patch("agent.grok_build.tail_grok_output", side_effect=fake_tail),
            patch("worker.monitor.update_process_offset") as update_offset,
            patch("worker.monitor.release_lease"),
        ):
            await _tail_and_process(
                "chat-1",
                {
                    "user_id": 1,
                    "vm_name": "vm",
                    "backend_type": "grok_build",
                    "work_dir": "/repo",
                    "session_id": "sess-1",
                    "updates_offset": 256,
                },
                "lambda-1",
                deadline_at=0,
            )

        self.assertEqual(captured["work_dir"], "/repo")
        self.assertEqual(captured["session_id"], "sess-1")
        self.assertEqual(captured["updates_offset"], 256)
        self.assertEqual(captured["existing_tool_call_ids"], {"tc-prior"})
        self.assertEqual(captured["existing_tool_result_ids"], {"tc-prior"})
        self.assertEqual(update_offset.call_args.kwargs["updates_offset"], 512)


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
