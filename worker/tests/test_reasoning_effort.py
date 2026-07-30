import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import (
    _build_claude_code_params,
    resolve_reasoning_effort,
)


def _message(role, content, message_id, reasoning_effort=None):
    return Message(
        id=message_id,
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        reasoning_effort=reasoning_effort,
    )


def _chat(messages, external_id=None):
    return Chat(
        id="chat-1",
        create_time=get_utc_iso8601_timestamp(),
        update_time=get_utc_iso8601_timestamp(),
        messages=messages,
        external_id=external_id,
        work_dir="/repo",
    )


class ReasoningEffortResolverTest(unittest.TestCase):
    def test_absent_effort_returns_none(self):
        self.assertIsNone(resolve_reasoning_effort([_message("user", "x", "m1")], "claude_code"))

    def test_newest_trailing_explicit_effort_wins(self):
        messages = [
            _message("user", "first", "m1", "low"),
            _message("user", "second", "m2"),
            _message("user", "third", "m3", "HIGH"),
        ]
        self.assertEqual(resolve_reasoning_effort(messages, "claude_code"), "high")

    def test_unsupported_backend_fails_clearly(self):
        for backend in ("perplexity", "openai", "codex"):
            with self.subTest(backend=backend):
                with self.assertRaisesRegex(ValueError, "only supported for claude_code"):
                    resolve_reasoning_effort([_message("user", "x", "m1", "high")], backend)

    def test_unknown_level_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "Unsupported reasoning effort"):
            resolve_reasoning_effort([_message("user", "x", "m1", "turbo")], "claude_code")


class ReasoningEffortCommandTest(unittest.TestCase):
    def setUp(self):
        self.vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")

    def test_claude_fresh_and_resume_commands_include_effort(self):
        bot = BotConfig(name="claude", backend="claude_code", model="model")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=self.vm):
            fresh = _build_claude_code_params(_chat([_message("user", "x", "m1", "max")]), "chat-1", 1, bot)
            resumed = _build_claude_code_params(_chat([_message("user", "x", "m1", "high")], external_id="session-1"), "chat-1", 1, bot)
        self.assertEqual(fresh["cmd"][-2:], ["--effort", "max"])
        self.assertEqual(resumed["cmd"][-2:], ["--effort", "high"])

    def test_commands_omit_effort_when_not_requested(self):
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=self.vm):
            params = _build_claude_code_params(
                _chat([_message("user", "x", "m1")]),
                "chat-1",
                1,
                BotConfig(name="claude", backend="claude_code"),
            )
        self.assertNotIn("--effort", params["cmd"])


if __name__ == "__main__":
    unittest.main()
