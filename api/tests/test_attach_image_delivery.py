import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.controller import chat as chat_controller
from storage.dto.chat import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


class AttachImageTelegramDeliveryTest(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        return SimpleNamespace(state=SimpleNamespace(user_id=123))

    def _chat(self, *, topic=None, running=False):
        return Chat(
            id="abc123",
            create_time=get_utc_iso8601_timestamp(),
            update_time=get_utc_iso8601_timestamp(),
            topic=topic,
            running=running,
            messages=[
                Message(
                    role="assistant",
                    content="done",
                    timestamp=get_utc_iso8601_timestamp(),
                    unix_timestamp=get_unix_timestamp(),
                )
            ],
        )

    async def test_attach_without_telegram_topic_does_not_deliver_or_mark(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "attached.png"
            image_path.write_bytes(b"png")
            chat = self._chat(topic=None)
            req = chat_controller.AttachImageRequest(chat_id="abc123", images=[str(image_path)])

            with (
                patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir),
                patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=chat)),
                patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()),
                patch.object(chat_controller, "send_telegram_photo_reference") as send_photo,
                patch("storage.service.telegram.resolve_target") as resolve_target,
            ):
                resp = await chat_controller.post_attach_image(req, self._request())

        resolve_target.assert_not_called()
        send_photo.assert_not_called()
        self.assertEqual(resp["telegram_delivered_images"], [])
        self.assertIsNone(chat.messages[0].telegram_delivered_images)

    async def test_attach_with_telegram_topic_delivers_and_marks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "attached.png"
            image_path.write_bytes(b"png")
            chat = self._chat(topic="dev")
            req = chat_controller.AttachImageRequest(chat_id="abc123", images=[str(image_path)], vm_name="ec2")
            vm_config = SimpleNamespace(name="ec2")

            with (
                patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir),
                patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=chat)),
                patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()),
                patch("storage.service.telegram.resolve_target", return_value=("token", "tg-chat", 42)) as resolve_target,
                patch.object(chat_controller, "_resolve_attach_vm_config", return_value=vm_config) as resolve_vm,
                patch.object(chat_controller, "send_telegram_photo_reference", return_value=True) as send_photo,
            ):
                resp = await chat_controller.post_attach_image(req, self._request())

        resolved_path = str(image_path.resolve())
        resolve_target.assert_called_once_with(123, topic="dev")
        resolve_vm.assert_called_once_with(123, chat, "ec2")
        send_photo.assert_called_once_with("token", "tg-chat", resolved_path, caption="done", topic_id=42, vm_config=vm_config)
        self.assertEqual(resp["telegram_delivered_images"], [resolved_path])
        self.assertEqual(chat.messages[0].telegram_delivered_images, [resolved_path])

    async def test_attach_with_running_chat_defers_telegram_delivery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "attached.png"
            image_path.write_bytes(b"png")
            chat = self._chat(topic="dev", running=True)
            req = chat_controller.AttachImageRequest(chat_id="abc123", images=[str(image_path)], vm_name="ec2")

            with (
                patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir),
                patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=chat)),
                patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()),
                patch("storage.service.telegram.resolve_target") as resolve_target,
                patch.object(chat_controller, "send_telegram_photo_reference") as send_photo,
            ):
                resp = await chat_controller.post_attach_image(req, self._request())

        resolved_path = str(image_path.resolve())
        resolve_target.assert_not_called()
        send_photo.assert_not_called()
        self.assertEqual(resp["telegram_delivered_images"], [])
        self.assertEqual(resp["images"], [resolved_path])
        self.assertIsNone(chat.messages[0].telegram_delivered_images)


if __name__ == "__main__":
    unittest.main()
