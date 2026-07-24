import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _build_claude_code_params, _start_detached


def _message(role: str, content: str, msg_id: str) -> Message:
    return Message(
        id=msg_id,
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )


def _chat(external_id=None, work_dir="/repo", skill=None) -> Chat:
    return Chat(
        id="chat-1",
        create_time=get_utc_iso8601_timestamp(),
        update_time=get_utc_iso8601_timestamp(),
        messages=[_message("user", "hello", "m1")],
        external_id=external_id,
        work_dir=work_dir,
        skill=skill,
    )


class ClaudeCodeEnvTest(unittest.TestCase):
    def test_env_always_disables_background_tasks(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_claude_code_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="claude_code", backend="claude_code"),
            )
        self.assertEqual(params["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")


class StartDetachedBackendSelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_backend_defaults_to_claude_code(self):
        chat = _chat()
        # A params dict with no prompt short-circuits _start_detached right
        # after backend selection, before any SSH/EC2/DynamoDB call.
        with patch(
            "worker.runner._build_claude_code_params", return_value={"prompt": None},
        ) as build_params:
            await _start_detached(chat, "chat-1", 1, BotConfig(name="default", backend=None))
        build_params.assert_called_once()

    async def test_unsupported_backend_raises(self):
        chat = _chat()
        with self.assertRaisesRegex(ValueError, "Unsupported detached backend"):
            await _start_detached(chat, "chat-1", 1, BotConfig(name="ghost", backend="claude_tui"))


if __name__ == "__main__":
    unittest.main()
