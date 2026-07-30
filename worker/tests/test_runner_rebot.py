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
        backend="claude_code",
        bot_name="sonnet",
        tier="tier2",
        external_id="session-abc",
    )
    defaults.update(overrides)
    return Chat(**defaults)


SONNET = BotConfig(name="sonnet", backend="claude_code", tier="tier2")


class RunChatRebotTest(unittest.TestCase):
    def _run(self, chat, resolved=SONNET, pinned=None, pinned_raises=None, **run_chat_kwargs):
        """Run run_chat with both bot resolvers stubbed.

        resolved  — what resolve_bot_config (the never-fails, tier2-fallback
                    resolver) returns.
        pinned    — what resolve_pinned_bot_config returns for a re-bot request;
                    None models a name that does not resolve to a runnable bot.
        """
        pin_kwargs = {"side_effect": pinned_raises} if pinned_raises else {"return_value": pinned}
        with (
            patch("worker.runner.chat_service.get_chat", new=AsyncMock(return_value=chat)),
            patch("worker.runner.chat_service.get_chat_by_id", new=AsyncMock(return_value=chat)),
            patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()),
            patch("worker.runner.agent_config.resolve_vm_config", return_value=Mock()),
            patch("worker.runner._send_telegram_user_message"),
            patch("worker.runner.agent_config.resolve_bot_config", return_value=resolved) as resolve,
            patch("worker.runner.agent_config.resolve_pinned_bot_config", **pin_kwargs) as resolve_pinned,
            patch("worker.runner._start_detached", new=AsyncMock()) as start_detached,
            patch("worker.runner._run_perplexity_inline", new=AsyncMock()) as run_perplexity,
        ):
            asyncio.run(runner.run_chat("user-1", "chat-1", **run_chat_kwargs))
        return Mock(resolve=resolve, resolve_pinned=resolve_pinned,
                    start_detached=start_detached, run_perplexity=run_perplexity)

    def test_same_backend_bot_change_is_accepted(self):
        """sonnet -> opus on an existing chat: the new bot wins, bot_name and
        tier follow it, and external_id is kept so the session resumes."""
        chat = _chat()
        opus = BotConfig(name="opus", backend="claude_code", tier="tier1")
        calls = self._run(chat, pinned=opus, bot_name="opus")

        self.assertEqual(chat.bot_name, "opus")
        self.assertEqual(chat.tier, "tier1")
        self.assertEqual(chat.backend, "claude_code")
        self.assertEqual(chat.external_id, "session-abc")
        self.assertEqual(calls.resolve_pinned.call_args.args[1], "opus")
        # The accepted bot comes from the pin resolver, not from the
        # tier2-fallback resolver, so a request that did not resolve can never
        # be mistaken for an honoured one.
        calls.resolve.assert_not_called()
        calls.start_detached.assert_awaited_once()

    def test_cross_backend_bot_change_is_refused(self):
        """sonnet -> px: the chat keeps its bot and still runs on claude_code."""
        chat = _chat()
        px = BotConfig(name="px", backend="perplexity", tier="tier3")
        calls = self._run(chat, resolved=SONNET, pinned=px, bot_name="px")

        self.assertEqual(chat.bot_name, "sonnet")
        self.assertEqual(chat.tier, "tier2")
        self.assertEqual(chat.backend, "claude_code")
        self.assertEqual(chat.external_id, "session-abc")
        self.assertEqual(calls.resolve.call_args.args[1], "sonnet")
        self.assertEqual(calls.resolve.call_args.kwargs["backend"], "claude_code")
        calls.run_perplexity.assert_not_awaited()
        calls.start_detached.assert_awaited_once()

    def test_unresolvable_requested_bot_leaves_the_chat_alone(self):
        """A disabled / unknown / wrong-tier bot name does not resolve, so the
        request is a no-op: without this the tier2 fallback (itself claude_code)
        would pass the backend check and silently move the chat onto it."""
        chat = _chat(bot_name="opus", tier="tier1")
        calls = self._run(chat, resolved=SONNET, pinned=None, bot_name="glm")

        self.assertEqual(chat.bot_name, "opus")
        self.assertEqual(chat.tier, "tier1")
        self.assertEqual(chat.external_id, "session-abc")
        self.assertEqual(calls.resolve.call_args.args[1], "opus")
        self.assertEqual(calls.resolve.call_args.kwargs["backend"], "claude_code")
        calls.start_detached.assert_awaited_once()

    def test_raising_pin_falls_through_to_the_sticky_path(self):
        """A pin that raises (a broken alias chain) is not an accepted re-bot,
        and it must not escape to run_chat's outer handler either: that
        handler's fallback config has no model and no credentials. The turn
        runs on the chat's own bot, fully resolved."""
        chat = _chat(bot_name="opus", tier="tier1")
        opus = BotConfig(name="opus", backend="claude_code", tier="tier1",
                         model="opus[1m]", base_url="https://relay/api", api_key="key")
        calls = self._run(chat, resolved=opus, pinned_raises=ValueError("circular ref"),
                          bot_name="alias")

        self.assertEqual(chat.bot_name, "opus")
        self.assertEqual(chat.tier, "tier1")
        self.assertEqual(chat.backend, "claude_code")
        self.assertEqual(chat.external_id, "session-abc")
        self.assertEqual(calls.resolve.call_args.args[1], "opus")
        self.assertEqual(calls.resolve.call_args.kwargs["backend"], "claude_code")
        # The real config reaches the launch, not the credential-less fallback.
        self.assertIs(calls.start_detached.await_args.args[3], opus)

    def test_no_bot_requested_keeps_the_chat_bot(self):
        """Without an explicit bot the chat stays on its own bot, so a changed
        user default never moves a running conversation."""
        chat = _chat()
        calls = self._run(chat, resolved=SONNET)

        self.assertEqual(chat.bot_name, "sonnet")
        self.assertEqual(calls.resolve.call_args.args[1], "sonnet")
        self.assertEqual(calls.resolve.call_args.kwargs["backend"], "claude_code")
        calls.resolve_pinned.assert_not_called()

    def test_same_bot_requested_is_not_a_rebot(self):
        chat = _chat()
        calls = self._run(chat, resolved=SONNET, bot_name="sonnet")

        self.assertEqual(calls.resolve.call_count, 1)
        self.assertEqual(calls.resolve.call_args.kwargs["backend"], "claude_code")
        calls.resolve_pinned.assert_not_called()

    def test_rebot_on_a_chat_without_a_persisted_backend_is_accepted(self):
        """Legacy chats predate chat.backend; there is nothing to compare, so
        the requested bot is used and its backend is stamped on the chat."""
        chat = _chat(backend=None)
        opus = BotConfig(name="opus", backend="claude_code", tier="tier1")
        self._run(chat, pinned=opus, bot_name="opus")

        self.assertEqual(chat.bot_name, "opus")
        self.assertEqual(chat.backend, "claude_code")


if __name__ == "__main__":
    unittest.main()
