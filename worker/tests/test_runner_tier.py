import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.dto.chat import Chat, Message
from storage.entity.dto import BotConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp

from worker import runner


def _chat(**overrides):
    message = Message(
        id="m1",
        role="user",
        content="hello",
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )
    defaults = dict(
        id="chat-1",
        create_time="",
        update_time="",
        messages=[message],
        topic="dev",
        skill="dev",
    )
    defaults.update(overrides)
    return Chat(**defaults)


class RunChatTierTest(unittest.TestCase):
    def _run(self, chat, bot_config=None, **run_chat_kwargs):
        bot_config = bot_config or BotConfig(name="bot-a", backend="claude_code")
        with (
            patch("worker.runner.chat_service.get_chat", new=AsyncMock(return_value=chat)),
            patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()),
            patch("worker.runner.agent_config.resolve_vm_config", return_value=Mock()),
            patch("worker.runner._send_telegram_user_message"),
            patch("worker.runner.agent_config.resolve_bot_config", return_value=bot_config) as resolve,
            patch("worker.runner._start_detached", new=AsyncMock()),
        ):
            asyncio.run(runner.run_chat("user-1", "chat-1", **run_chat_kwargs))
        return resolve

    def test_no_filters_dispatch_resolves_tier_none_regardless_of_skill(self):
        """A dispatch with no explicit tier passes tier=None through to
        resolve_bot_config (which itself defaults to tier2); the skill must
        not influence tier resolution."""
        chat = _chat(skill="dev")
        resolve = self._run(chat, skill="dev")
        self.assertIsNone(resolve.call_args.kwargs["tier"])

    def test_explicit_bot_tier_overrides(self):
        chat = _chat(skill="dev")
        resolve = self._run(chat, skill="dev", bot_tier="tier0")
        self.assertEqual(resolve.call_args.kwargs["tier"], "tier0")

    def test_resolved_tier_persisted_on_chat(self):
        """The tier actually resolved on the returned bot config (not the
        filter passed in) is what gets persisted on the chat record."""
        chat = _chat(skill="dev")
        bot_config = BotConfig(name="bot-a", backend="claude_code", tier="tier1")
        self._run(chat, bot_config=bot_config, skill="dev")
        self.assertEqual(chat.tier, "tier1")

    def test_default_tier_resolution_persisted_when_bot_config_has_no_tier(self):
        """A bot config with no explicit tier resolves (via tier_of) to
        tier3, and that default must still be persisted on the chat."""
        chat = _chat(skill="dev")
        bot_config = BotConfig(name="bot-a", backend="claude_code", tier=None)
        self._run(chat, bot_config=bot_config, skill="dev")
        self.assertEqual(chat.tier, "tier3")

    def test_tier_not_overwritten_once_set(self):
        """tier follows the same once-set-stays-set rule as backend/bot_name:
        a chat's tier is fixed at first dispatch."""
        chat = _chat(skill="dev", tier="tier1")
        bot_config = BotConfig(name="bot-a", backend="claude_code", tier="tier2")
        self._run(chat, bot_config=bot_config, skill="dev")
        self.assertEqual(chat.tier, "tier1")

    def test_unsupported_inline_effort_resets_chat_and_records_error(self):
        chat = _chat(messages=[Message(
            id="m1",
            role="user",
            content="hello",
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
            reasoning_effort="high",
        )])
        bot_config = BotConfig(name="openai", backend="openai")
        with (
            patch("worker.runner.chat_service.get_chat", new=AsyncMock(return_value=chat)),
            patch("worker.runner.chat_service.get_chat_by_id", new=AsyncMock(return_value=chat)),
            patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()) as save_chat,
            patch("worker.runner.agent_config.resolve_vm_config", return_value=Mock()),
            patch("worker.runner._send_telegram_user_message"),
            patch("worker.runner.agent_config.resolve_bot_config", return_value=bot_config),
            patch("worker.runner._run_openai_inline", new=AsyncMock()) as run_openai,
        ):
            with self.assertRaisesRegex(ValueError, "only supported for claude_code and codex"):
                asyncio.run(runner.run_chat("user-1", "chat-1"))

        self.assertFalse(chat.running)
        self.assertEqual(chat.messages[-1].role, "assistant")
        self.assertIn("Backend launch failed: ValueError", chat.messages[-1].content)
        self.assertIn("only supported for claude_code and codex", chat.messages[-1].content)
        run_openai.assert_not_awaited()
        self.assertGreaterEqual(save_chat.await_count, 3)


if __name__ == "__main__":
    unittest.main()
