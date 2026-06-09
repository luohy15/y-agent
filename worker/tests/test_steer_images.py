import unittest
from unittest.mock import Mock, patch

from worker.runner import make_steer_checker


class _Msg:
    def __init__(self, role, content, msg_id, images=None):
        self.role = role
        self.content = content
        self.id = msg_id
        self.images = images


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

    def test_restart_codex_forwards_steer_images(self):
        import worker.monitor as monitor

        async def run():
            with (
                patch("agent.config.resolve_vm_config", return_value=Mock()),
                patch("agent.config.resolve_bot_config", return_value=Mock(model=None)),
                patch("agent.codex.start_detached_codex_ssh") as start,
                patch("worker.monitor.update_process_offset"),
                patch("worker.monitor.release_lease"),
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


if __name__ == "__main__":
    unittest.main()
