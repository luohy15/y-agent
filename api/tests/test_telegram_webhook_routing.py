"""Unit tests for api.controller.telegram webhook routing.

Covers the cheap pure-branching arms of the webhook handler:
  - secret-token verification (unconfigured -> reject; mismatch -> reject)
  - empty-body / empty-text early returns
  - explicit `/{chat_id} <msg>` routing to _handle_routed_message
  - the route-prefix regexes (chat_id 6-hex vs todo all-digits)

DB / Telegram-API calls are mocked or routed into mocked async helpers; nothing
hits a live DB or the network.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from api.controller import telegram as tg
from storage.dto.chat import Chat
from storage.service.chat import HANDOFF_REMINDER_MARKER


def _chat(*, id, context_window=None, input_tokens=None, topic=None, running=False):
    return Chat(
        id=id,
        create_time="2026-07-30T00:00:00Z",
        update_time="2026-07-30T00:00:00Z",
        messages=[],
        topic=topic,
        running=running,
        context_window=context_window,
        input_tokens=input_tokens,
    )


class FakeRequest:
    def __init__(self, *, secret_header="", body=None):
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret_header}
        self._body = body if body is not None else {}

    async def json(self):
        return self._body


def _message_body(text, *, chat_id=10, user_id=20):
    return {"message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": text}}


class TelegramWebhookSecretTest(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_secret_rejects(self):
        with patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", ""):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="anything"))
        self.assertEqual(resp, {"ok": False})

    async def test_mismatched_secret_rejects(self):
        with patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="wrong"))
        self.assertEqual(resp, {"ok": False})

    async def test_no_message_returns_ok(self):
        with patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="right", body={}))
        self.assertEqual(resp, {"ok": True})

    async def test_empty_text_returns_ok(self):
        body = _message_body("   ")  # whitespace -> empty after strip, no photo
        with patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="right", body=body))
        self.assertEqual(resp, {"ok": True})


class TelegramWebhookRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_id_prefix_routes_to_handle_routed_message(self):
        body = _message_body("/ba4988 hello there")
        routed = AsyncMock(return_value={"ok": True})
        with (
            patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"),
            patch.object(tg, "_handle_routed_message", routed),
        ):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="right", body=body))
        self.assertEqual(resp, {"ok": True})
        routed.assert_called_once()
        # Positional: (tg_chat_id, tg_user_id, target_chat_id, body)
        args = routed.call_args.args
        self.assertEqual(args[2], "ba4988")
        self.assertEqual(args[3], "hello there")

    async def test_start_command_sends_welcome(self):
        body = _message_body("/start")
        send = AsyncMock()
        with (
            patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"),
            patch.object(tg, "_send_message", send),
        ):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="right", body=body))
        self.assertEqual(resp, {"ok": True})
        send.assert_called_once()
        self.assertIn("Welcome", send.call_args.args[1])

    async def test_clear_restarts_manager_with_standard_bootstrap_flow(self):
        body = _message_body("/clear")
        user = type("User", (), {"id": 42})()
        restart = AsyncMock()
        send = AsyncMock()
        with (
            patch.object(tg, "TELEGRAM_WEBHOOK_SECRET", "right"),
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch("storage.service.chat.restart_manager_session", restart),
            patch.object(tg, "_send_message", send),
        ):
            resp = await tg.telegram_webhook(FakeRequest(secret_header="right", body=body))
        self.assertEqual(resp, {"ok": True})
        restart.assert_awaited_once_with(42)
        send.assert_awaited_once_with(10, "New session started.", message_thread_id=None)


class TelegramHandoffReminderTest(unittest.IsolatedAsyncioTestCase):
    """Covers the three existing-chat telegram write sites that append the
    context-handoff reminder: _handle_routed_message, and both existing-chat
    branches of _handle_message (the manager-steer branch, exercised via a
    running=True root chat, and the plain-append branch, via running=False).
    The new-chat branch is untouched by design (context_window is always
    None for a brand-new chat)."""

    async def test_routed_message_into_over_threshold_chat_gets_marker(self):
        user = type("User", (), {"id": 42})()
        # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
        target_chat = _chat(id="ba4988", context_window=1000, input_tokens=600)  # 600 > 500
        save = AsyncMock()
        with (
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch("storage.repository.chat.get_chat", AsyncMock(return_value=target_chat)),
            patch("storage.repository.chat.save_chat_by_id", save),
            patch("storage.service.chat.send_chat_message", MagicMock()),
        ):
            resp = await tg._handle_routed_message(10, 20, "ba4988", "hello there")
        self.assertEqual(resp, {"ok": True})
        saved_content = save.call_args.args[0].messages[-1].content
        self.assertIn(HANDOFF_REMINDER_MARKER, saved_content)

    async def test_routed_message_into_under_threshold_chat_unchanged(self):
        user = type("User", (), {"id": 42})()
        # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
        target_chat = _chat(id="ba4988", context_window=1000, input_tokens=400)  # 400 <= 500
        save = AsyncMock()
        with (
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch("storage.repository.chat.get_chat", AsyncMock(return_value=target_chat)),
            patch("storage.repository.chat.save_chat_by_id", save),
            patch("storage.service.chat.send_chat_message", MagicMock()),
        ):
            await tg._handle_routed_message(10, 20, "ba4988", "hello there")
        saved_content = save.call_args.args[0].messages[-1].content
        self.assertEqual(saved_content, "hello there")

    async def test_existing_chat_dm_into_over_threshold_chat_gets_marker(self):
        user = type("User", (), {"id": 42, "email": "u@example.com"})()
        # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
        existing = _chat(id="c1", topic="dev", running=False, context_window=1000, input_tokens=600)
        save = AsyncMock()
        with (
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch.object(tg, "find_latest_chat_by_topic", return_value=existing),
            patch("storage.repository.chat.save_chat_by_id", save),
            patch("storage.service.chat.send_chat_message", MagicMock()),
        ):
            await tg._handle_message(10, 20, "hello there")
        saved_content = save.call_args.args[0].messages[-1].content
        self.assertIn(HANDOFF_REMINDER_MARKER, saved_content)

    async def test_manager_steer_into_over_threshold_running_chat_gets_marker(self):
        # topic defaults to 'manager' when there is no forum thread_id, and
        # running=True routes through the steer branch (distinct code path
        # from the plain existing-chat append above).
        user = type("User", (), {"id": 42, "email": "u@example.com"})()
        # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
        existing = _chat(id="m1", topic="manager", running=True, context_window=1000, input_tokens=600)
        save = AsyncMock()
        with (
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch.object(tg, "find_latest_chat_by_topic", return_value=existing),
            patch("storage.repository.chat.save_chat_by_id", save),
        ):
            resp = await tg._handle_message(10, 20, "hello there")
        self.assertEqual(resp, {"ok": True})
        saved_content = save.call_args.args[0].messages[-1].content
        self.assertIn(HANDOFF_REMINDER_MARKER, saved_content)

    async def test_new_chat_dm_does_not_get_marker(self):
        # A brand-new chat has context_window=None -> the reminder is a
        # structural no-op; the new-chat branch is not wired to the helper.
        user = type("User", (), {"id": 42, "email": "u@example.com"})()
        save = AsyncMock()
        with (
            patch.object(tg, "get_user_by_telegram_id", return_value=user),
            patch.object(tg, "find_latest_chat_by_topic", return_value=None),
            patch("storage.repository.chat.save_chat", save),
            patch("storage.repository.chat.release_topic", MagicMock(return_value=0)),
            patch("storage.service.chat.send_chat_message", MagicMock()),
        ):
            await tg._handle_message(10, 20, "hello there")
        saved_content = save.call_args.args[1].messages[-1].content
        self.assertEqual(saved_content, "hello there")


class TelegramRoutePrefixRegexTest(unittest.TestCase):
    def test_chat_id_prefix_requires_six_hex_and_whitespace(self):
        self.assertEqual(tg._TG_ROUTE_PREFIX_RE.match("/ba4988 hi").group(1), "ba4988")
        # 6 all-digit hex still matches the chat_id form.
        self.assertEqual(tg._TG_ROUTE_PREFIX_RE.match("/123456 hi").group(1), "123456")
        # Fewer than 6 chars, or no separator -> no match.
        self.assertIsNone(tg._TG_ROUTE_PREFIX_RE.match("/ba49 hi"))
        self.assertIsNone(tg._TG_ROUTE_PREFIX_RE.match("/ba4988hi"))
        # Non-hex char.
        self.assertIsNone(tg._TG_ROUTE_PREFIX_RE.match("/zzzzzz hi"))

    def test_todo_prefix_matches_all_digits(self):
        self.assertEqual(tg._TG_ROUTE_TODO_PREFIX_RE.match("/1938 hi").group(1), "1938")
        self.assertIsNone(tg._TG_ROUTE_TODO_PREFIX_RE.match("/abc hi"))
        self.assertIsNone(tg._TG_ROUTE_TODO_PREFIX_RE.match("/1938hi"))


if __name__ == "__main__":
    unittest.main()
