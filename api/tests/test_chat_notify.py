"""Unit tests for api.controller.chat.post_chat_notify — the y-chat cross-session
trace/notify contract.

Covers the pure branching that downstream sessions depend on:
  - trace-prefix construction `[trace:.. from:.. to:.. from_chat:.. to_chat:..]`
  - root-topic ('manager') callback rejection (both arms) + --new escape hatch
  - chat resolution precedence: explicit chat_id > topic+trace lookup > new
  - topic-mismatch / work_dir-mismatch 400s
  - already-running -> steer (don't enqueue a new worker task)
  - handoff-reminder append on the existing-chat branch (over/under threshold)

DB / SSH / vm-config are mocked; nothing touches a real database.
"""

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from api.controller import chat as chat_controller
from storage.dto.chat import Chat
from storage.service.chat import HANDOFF_REMINDER_MARKER


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _existing_chat(*, id, topic=None, work_dir=None, running=False, messages=None, context_window=None, input_tokens=None):
    """Build a real Chat DTO for the `existing`/`found` notify-target fixture.

    Defaults to no usage data (context_window=None), matching the pre-reminder
    test fixtures exactly: `context_usage_ratio()` is None so
    `maybe_append_handoff_reminder` is a no-op.
    """
    return Chat(
        id=id,
        create_time="2026-07-30T00:00:00Z",
        update_time="2026-07-30T00:00:00Z",
        messages=messages or [],
        topic=topic,
        work_dir=work_dir,
        running=running,
        context_window=context_window,
        input_tokens=input_tokens,
    )


class PostChatNotifyTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self, *, existing=None, found=None, new_chat_id="newchat"):
        """Build an ExitStack of patches isolating post_chat_notify from DB/SSH.

        Returns a namespace carrying the live mocks so tests can assert on calls.
        """
        stack = ExitStack()
        new_chat = SimpleNamespace(
            id=new_chat_id, topic=None, skill=None, running=False, work_dir=None, messages=[]
        )
        get_chat_by_id = AsyncMock(return_value=existing)
        create_chat = AsyncMock(return_value=new_chat)
        append_message = AsyncMock(return_value=existing)
        send = MagicMock()
        find = MagicMock(return_value=found)
        save_by_id = AsyncMock()
        save_chat = AsyncMock()
        release = MagicMock(return_value=0)

        stack.enter_context(patch.object(chat_controller.chat_service, "get_chat_by_id", get_chat_by_id))
        stack.enter_context(patch.object(chat_controller.chat_service, "create_chat", create_chat))
        stack.enter_context(patch.object(chat_controller.chat_service, "append_message", append_message))
        stack.enter_context(patch.object(chat_controller, "send_chat_message", send))
        stack.enter_context(patch.object(chat_controller, "generate_id", lambda: new_chat_id))
        stack.enter_context(patch.object(chat_controller, "resolve_message_image_paths", MagicMock(return_value=[])))
        stack.enter_context(patch("storage.repository.chat.find_chat_by_topic_and_trace", find))
        stack.enter_context(patch("storage.repository.chat.save_chat_by_id", save_by_id))
        stack.enter_context(patch("storage.repository.chat.save_chat", save_chat))
        stack.enter_context(patch("storage.repository.chat.release_topic", release))
        stack.enter_context(patch("agent.config.resolve_vm_config", MagicMock(return_value=None)))

        return SimpleNamespace(
            stack=stack, new_chat=new_chat, get_chat_by_id=get_chat_by_id,
            create_chat=create_chat, append_message=append_message, send=send,
            find=find, save_by_id=save_by_id, save_chat=save_chat, release=release,
        )

    @staticmethod
    def _created_content(m) -> str:
        return m.create_chat.call_args.kwargs["messages"][0].content

    @staticmethod
    def _appended_content(m) -> str:
        return m.append_message.call_args.args[1].content

    @staticmethod
    def _created_message(m):
        return m.create_chat.call_args.kwargs["messages"][0]

    # --- trace-prefix construction -------------------------------------------------

    async def test_full_trace_prefix_on_new_chat(self):
        req = chat_controller.NotifyRequest(
            message="hello", topic="dev", trace_id="2484",
            from_topic="manager", from_chat_id="caller1",
        )
        m = self._patches(found=None, new_chat_id="newchat")
        with m.stack:
            resp = await chat_controller.post_chat_notify(req, _request())

        self.assertEqual(resp.chat_id, "newchat")
        self.assertEqual(resp.trace_id, "2484")
        self.assertEqual(
            self._created_content(m),
            "[trace:2484 from:manager to:dev from_chat:caller1 to_chat:newchat]\nhello",
        )
        # skill defaults to the (non-root) topic; worker enqueued for a fresh chat.
        m.send.assert_called_once()
        self.assertEqual(m.send.call_args.kwargs["skill"], "dev")
        self.assertEqual(m.send.call_args.kwargs["topic"], "dev")
        self.assertEqual(m.send.call_args.kwargs["trace_id"], "2484")

    async def test_minimal_prefix_only_to_chat(self):
        # Bare anonymous dispatch: only the to_chat anchor is present.
        req = chat_controller.NotifyRequest(message="ping")
        m = self._patches()
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())

        self.assertEqual(self._created_content(m), "[to_chat:newchat]\nping")

    async def test_reasoning_effort_is_stored_on_notify_message(self):
        req = chat_controller.NotifyRequest(message="ping", reasoning_effort="HIGH")
        m = self._patches()
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(self._created_message(m).reasoning_effort, "high")

    # --- root-topic ('manager') callback rejection ---------------------------------

    async def test_existing_manager_chat_rejects_callback(self):
        existing = _existing_chat(id="m1", topic="manager", work_dir=None, running=False)
        req = chat_controller.NotifyRequest(message="result", chat_id="m1")
        m = self._patches(existing=existing)
        with m.stack:
            with self.assertRaises(HTTPException) as ctx:
                await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(ctx.exception.status_code, 400)
        m.send.assert_not_called()

    async def test_new_manager_topic_without_new_rejects(self):
        req = chat_controller.NotifyRequest(message="hi", topic="manager")
        m = self._patches()
        with m.stack:
            with self.assertRaises(HTTPException) as ctx:
                await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_new_manager_topic_with_force_new_allowed(self):
        req = chat_controller.NotifyRequest(message="fresh", topic="manager", force_new=True)
        m = self._patches()
        with m.stack:
            resp = await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(resp.chat_id, "newchat")
        self.assertEqual(self._created_content(m), "[to:manager to_chat:newchat]\nfresh")
        # manager is a root topic with no trace -> singleton-ownership release runs.
        m.release.assert_called_once()
        m.send.assert_called_once()

    # --- chat resolution precedence ------------------------------------------------

    async def test_explicit_chat_id_takes_precedence_over_topic_trace(self):
        existing = _existing_chat(id="c1", topic="dev", work_dir=None, running=False)
        req = chat_controller.NotifyRequest(
            message="x", chat_id="c1", topic="dev", trace_id="2484",
        )
        m = self._patches(existing=existing)
        with m.stack:
            resp = await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(resp.chat_id, "c1")
        # topic+trace lookup must be skipped when chat_id is explicit.
        m.find.assert_not_called()

    async def test_topic_trace_lookup_resolves_existing_chat(self):
        found = _existing_chat(id="f9", topic="dev", work_dir=None, running=False)
        req = chat_controller.NotifyRequest(message="x", topic="dev", trace_id="2484")
        m = self._patches(existing=found, found=found)
        with m.stack:
            resp = await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(resp.chat_id, "f9")
        m.find.assert_called_once_with(123, "dev", "2484")
        # appended to the resolved chat, not created fresh.
        m.create_chat.assert_not_called()
        self.assertTrue(self._appended_content(m).startswith("[trace:2484 to:dev to_chat:f9]"))

    # --- mismatch guards -----------------------------------------------------------

    async def test_topic_mismatch_rejected(self):
        existing = _existing_chat(id="c1", topic="dev", work_dir=None, running=False)
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="ops")
        m = self._patches(existing=existing)
        with m.stack:
            with self.assertRaises(HTTPException) as ctx:
                await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("topic mismatch", ctx.exception.detail)

    async def test_work_dir_mismatch_rejected(self):
        existing = _existing_chat(id="c1", topic="dev", work_dir="/a", running=False)
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="dev", work_dir="/b")
        m = self._patches(existing=existing)
        with m.stack:
            with self.assertRaises(HTTPException) as ctx:
                await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("work_dir mismatch", ctx.exception.detail)
        m.append_message.assert_not_called()

    # --- already-running -> steer (no new worker task) -----------------------------

    async def test_running_chat_does_not_enqueue_worker(self):
        existing = _existing_chat(id="c1", topic="dev", work_dir=None, running=True)
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="dev")
        m = self._patches(existing=existing)
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())
        m.send.assert_not_called()

    async def test_idle_existing_chat_enqueues_worker(self):
        existing = _existing_chat(id="c1", topic="dev", work_dir=None, running=False)
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="dev")
        m = self._patches(existing=existing)
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())
        m.send.assert_called_once()

    # --- handoff reminder ------------------------------------------------------------

    async def test_over_threshold_existing_chat_appends_reminder(self):
        existing = _existing_chat(
            id="c1", topic="dev", running=False,
            # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
            context_window=1000, input_tokens=600,  # 600 > 500 threshold
        )
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="dev")
        m = self._patches(existing=existing)
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())
        self.assertIn(HANDOFF_REMINDER_MARKER, self._appended_content(m))

    async def test_under_threshold_existing_chat_content_unchanged(self):
        existing = _existing_chat(
            id="c1", topic="dev", running=False,
            # window 1000 -> min(0.5 * 1000, 200_000) = 500 token threshold
            context_window=1000, input_tokens=400,  # 400 <= 500 threshold
        )
        req = chat_controller.NotifyRequest(message="x", chat_id="c1", topic="dev")
        m = self._patches(existing=existing)
        with m.stack:
            await chat_controller.post_chat_notify(req, _request())
        self.assertEqual(self._appended_content(m), "[to:dev to_chat:c1]\nx")


if __name__ == "__main__":
    unittest.main()
