import unittest
from unittest.mock import AsyncMock, Mock, patch

from worker.runner import _pending_user_text_and_images, make_steer_checker


class _Msg:
    def __init__(self, role, content, msg_id, images=None, reasoning_effort=None):
        self.role = role
        self.content = content
        self.id = msg_id
        self.images = images
        self.reasoning_effort = reasoning_effort


class _Chat:
    def __init__(self, messages):
        self.messages = messages


class SteerImagesSmokeTest(unittest.TestCase):
    def test_make_steer_checker_returns_images(self):
        chat = _Chat([
            _Msg("user", "initial", "m1"),
            _Msg("user", "describe", "m2", ["s3://bucket/images/photo.png"]),
        ])
        with patch("worker.runner.chat_service.get_chat_by_id_sync", return_value=chat):
            check = make_steer_checker("chat-1", {"m1"})
            self.assertEqual(check(), [("describe", "m2", ["s3://bucket/images/photo.png"])])
            self.assertEqual(check(), [])

    def test_make_steer_checker_unclaim_resurfaces_message(self):
        chat = _Chat([_Msg("user", "hello", "m1")])
        with patch("worker.runner.chat_service.get_chat_by_id_sync", return_value=chat):
            check = make_steer_checker("chat-1", set())
            self.assertEqual(check(), [("hello", "m1", [])])
            self.assertEqual(check(), [])
            # A failed delivery must release the claim so the next call
            # re-surfaces the message instead of treating it as delivered
            # forever (plan-2662-steer-race.md, sub-task 2).
            check.unclaim("m1")
            self.assertEqual(check(), [("hello", "m1", [])])

    def test_restart_codex_forwards_steer_images(self):
        import worker.monitor as monitor

        async def run():
            chat = _Chat([_Msg("user", "describe", "m2")])
            with (
                patch("agent.config.resolve_vm_config", return_value=Mock()),
                patch("agent.config.resolve_bot_config", return_value=Mock(model=None)),
                patch("agent.codex.start_detached_codex_ssh") as start,
                patch("worker.monitor.update_process_offset"),
                patch("worker.monitor.release_lease"),
                patch("storage.service.chat.get_chat_by_id", AsyncMock(return_value=chat)),
            ):
                await monitor._restart_codex_with_steer(
                    "chat-1",
                    {"user_id": 1, "vm_name": "vm", "backend_type": "codex"},
                    {
                        "thread_id": "thread-1",
                        "last_message_id": "m2",
                        "steer_text": "describe",
                        "steer_images": ["s3://bucket/images/photo.png"],
                        "consumed_steer_ids": ["m2"],
                    },
                )
                self.assertEqual(start.await_args.kwargs["images"], ["s3://bucket/images/photo.png"])

        import asyncio
        asyncio.run(run())


class PendingUserTextAndImagesTest(unittest.TestCase):
    def test_gathers_all_trailing_user_messages_not_just_latest(self):
        messages = [
            _Msg("assistant", "prior reply", "a1"),
            _Msg("user", "first", "m1", ["img1.png"]),
            _Msg("user", "second", "m2", ["img2.png"]),
        ]
        text, images = _pending_user_text_and_images(messages)
        self.assertEqual(text, "first\n\nsecond")
        self.assertEqual(images, ["img1.png", "img2.png"])

    def test_single_trailing_user_message_behaves_like_before(self):
        messages = [
            _Msg("assistant", "prior reply", "a1"),
            _Msg("user", "only", "m1", ["img.png"]),
        ]
        text, images = _pending_user_text_and_images(messages)
        self.assertEqual(text, "only")
        self.assertEqual(images, ["img.png"])

    def test_no_trailing_user_message_returns_empty(self):
        messages = [_Msg("user", "old", "m1"), _Msg("assistant", "done", "a1")]
        text, images = _pending_user_text_and_images(messages)
        self.assertEqual(text, "")
        self.assertEqual(images, [])

    def test_empty_messages_returns_empty(self):
        text, images = _pending_user_text_and_images([])
        self.assertEqual(text, "")
        self.assertEqual(images, [])


if __name__ == "__main__":
    unittest.main()
