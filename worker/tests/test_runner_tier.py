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
    def _run(self, chat, **run_chat_kwargs):
        bot_config = BotConfig(name="bot-a", backend="claude_code")
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


if __name__ == "__main__":
    unittest.main()
