import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.controller import chat as chat_controller
from storage.dto.chat import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


class ChatImagesApiTest(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        return SimpleNamespace(state=SimpleNamespace(user_id=123))

    def _chat(self, chat_id="abc123"):
        return Chat(id=chat_id, create_time=get_utc_iso8601_timestamp(), update_time=get_utc_iso8601_timestamp(), messages=[])

    def _message(self, role="assistant", content="done", images=None):
        return Message(role=role, content=content, images=images, timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp())

    async def test_create_chat_accepts_image_uploads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            req = chat_controller.CreateChatRequest(
                prompt="see image",
                image_uploads=[chat_controller.ImageUpload(filename="photo.png", content_base64=base64.b64encode(b"png").decode("ascii"))],
            )
            saved = {}

            async def create_chat(user_id, messages, chat_id):
                saved["message"] = messages[0]
                return self._chat(chat_id)

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "create_chat", new=AsyncMock(side_effect=create_chat)), \
                 patch("storage.repository.chat.save_chat", new=AsyncMock()), \
                 patch.object(chat_controller, "send_chat_message"):
                await chat_controller.post_create_chat(req, self._request())

            images = saved["message"].images
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0].startswith(str(assets_dir)))
            self.assertEqual(Path(images[0]).read_bytes(), b"png")
            self.assertNotIn("content_base64", saved["message"].to_dict())

    async def test_send_message_accepts_existing_image_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "photo.jpg"
            image_path.write_bytes(b"jpg")
            existing = self._chat()
            req = chat_controller.SendMessageRequest(chat_id="abc123", prompt="existing", images=[str(image_path)])

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=existing)), \
                 patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()), \
                 patch.object(chat_controller, "send_chat_message"):
                await chat_controller.post_send_message(req, self._request())

            self.assertEqual(existing.messages[-1].images, [str(image_path.resolve())])

    async def test_send_message_accepts_missing_ec2_asset_image_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "missing-on-lambda.jpg"
            existing = self._chat()
            req = chat_controller.SendMessageRequest(chat_id="abc123", prompt="existing", images=[str(image_path)])

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=existing)), \
                 patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()), \
                 patch.object(chat_controller, "send_chat_message"):
                await chat_controller.post_send_message(req, self._request())

            self.assertEqual(existing.messages[-1].images, [str(image_path.resolve())])

    async def test_notify_accepts_image_uploads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            req = chat_controller.NotifyRequest(
                message="notify image",
                topic="dev",
                image_uploads=[chat_controller.ImageUpload(filename="photo.webp", content_base64=base64.b64encode(b"webp").decode("ascii"))],
            )
            saved = {}

            async def create_chat(user_id, messages, chat_id):
                saved["message"] = messages[0]
                chat = self._chat(chat_id)
                chat.messages = messages
                return chat

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "create_chat", new=AsyncMock(side_effect=create_chat)), \
                 patch("storage.repository.chat.save_chat", new=AsyncMock()), \
                 patch("storage.repository.chat.release_topic", return_value=0), \
                 patch.object(chat_controller, "send_chat_message"):
                await chat_controller.post_chat_notify(req, self._request())

            images = saved["message"].images
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0].startswith(str(assets_dir)))
            self.assertNotIn("data:", str(saved["message"].to_dict()))

    async def test_attach_image_updates_latest_assistant_message(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            image_path = assets_dir / "attached.png"
            image_path.write_bytes(b"png")
            existing = self._chat()
            existing.messages = [
                self._message("assistant", "old", ["https://example.com/old.jpg"]),
                self._message("user", "next"),
                self._message("assistant", "new"),
            ]
            req = chat_controller.AttachImageRequest(chat_id="abc123", images=[str(image_path), str(image_path)])

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=existing)), \
                 patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()) as save_chat:
                resp = await chat_controller.post_attach_image(req, self._request())

            self.assertEqual(resp["count"], 1)
            self.assertEqual(existing.messages[0].images, ["https://example.com/old.jpg"])
            self.assertEqual(existing.messages[-1].images, [str(image_path.resolve())])
            save_chat.assert_awaited_once_with(existing)

    async def test_attach_image_accepts_image_uploads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir).resolve()
            existing = self._chat()
            existing.messages = [self._message("assistant", "new")]
            req = chat_controller.AttachImageRequest(
                chat_id="abc123",
                image_uploads=[chat_controller.ImageUpload(filename="attached.png", content_base64=base64.b64encode(b"png").decode("ascii"))],
            )

            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=existing)), \
                 patch("storage.repository.chat.save_chat_by_id", new=AsyncMock()) as save_chat:
                resp = await chat_controller.post_attach_image(req, self._request())

            self.assertEqual(resp["count"], 1)
            images = existing.messages[-1].images
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0].startswith(str(assets_dir)))
            self.assertEqual(Path(images[0]).read_bytes(), b"png")
            save_chat.assert_awaited_once_with(existing)

    async def test_attach_image_requires_assistant_message(self):
        existing = self._chat()
        existing.messages = [self._message("user", "hello")]
        req = chat_controller.AttachImageRequest(chat_id="abc123", images=["https://example.com/a.png"])

        with patch.object(chat_controller.chat_service, "get_chat", new=AsyncMock(return_value=existing)):
            with self.assertRaises(Exception) as ctx:
                await chat_controller.post_attach_image(req, self._request())

        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
