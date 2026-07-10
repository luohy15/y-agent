"""Focused tests for manager session restart creation."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.service import chat as chat_service


class RestartManagerSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_creates_and_dispatches_bootstrapped_manager(self):
        created_chat = type("Chat", (), {"id": "fresh", "topic": None, "running": False})()
        create = AsyncMock(return_value=created_chat)
        save = AsyncMock()
        release = Mock()
        send = Mock()
        with (
            patch.object(chat_service, "create_chat", create),
            patch.object(chat_service.chat_repo, "save_chat_by_id", save),
            patch.object(chat_service.chat_repo, "release_topic", release),
            patch.object(chat_service, "send_chat_message", send),
        ):
            chat = await chat_service.restart_manager_session(42)

        self.assertIs(chat, created_chat)
        self.assertEqual(chat.topic, "manager")
        self.assertTrue(chat.running)
        bootstrap = create.await_args.kwargs["messages"][0]
        self.assertEqual(bootstrap.role, "user")
        self.assertEqual(bootstrap.content, "load manager skill")
        save.assert_awaited_once_with(created_chat)
        release.assert_called_once_with(42, "manager", except_chat_id="fresh")
        send.assert_called_once_with("fresh", user_id=42, topic="manager", bot_tier="tier1")
