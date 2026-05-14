import unittest
from unittest.mock import patch

from agent.config import resolve_bot_config
from storage.entity.dto import BotConfig


class ResolveBotConfigTest(unittest.TestCase):
    def test_backend_identity_ignores_mismatched_default_config(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
            BotConfig(name="claude_code", backend="claude_code", model="sonnet"),
        ]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "claude_code")
        self.assertEqual(config.backend, "claude_code")
        self.assertEqual(config.model, "sonnet")

    def test_backend_only_fallback_does_not_reuse_mismatched_model(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
        ]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "claude_code")
        self.assertEqual(config.model, "")

    def test_without_backend_preserves_default_resolution(self):
        default_config = BotConfig(name="default", backend="codex", model="gpt-5.4")

        with patch("agent.config.bot_service.get_config", return_value=default_config):
            config = resolve_bot_config(1)

        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "gpt-5.4")


if __name__ == "__main__":
    unittest.main()
