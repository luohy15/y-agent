import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _build_claude_code_params, _build_claude_tui_params

RELAY_URL = "https://cc1.yovy.app"


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


class ClaudeTuiEnvTest(unittest.TestCase):
    def test_env_assumes_first_party_base_url_when_relay_configured(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_claude_tui_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="claude_tui_relay", backend="claude_tui",
                          base_url=RELAY_URL, api_key="cr_x"),
            )
        self.assertEqual(params["env"]["ANTHROPIC_BASE_URL"], RELAY_URL)
        self.assertEqual(params["env"]["_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"], "1")

    def test_env_omits_first_party_flag_without_base_url(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_claude_tui_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="claude_tui", backend="claude_tui"),
            )
        env = params["env"] or {}
        self.assertNotIn("_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def test_env_always_disables_background_tasks(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_claude_tui_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="claude_tui", backend="claude_tui"),
            )
        self.assertEqual(params["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")


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


if __name__ == "__main__":
    unittest.main()
