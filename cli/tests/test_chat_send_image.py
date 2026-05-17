import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.chat.click import chat_group


class ChatSendImageCliTest(unittest.TestCase):
    def test_chat_message_stages_image_and_sends_asset_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"jpg")
            assets_dir = Path(tmp_dir) / "assets" / "images"

            with patch("yagent.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch("yagent.commands.chat.click.api_request") as api_request:
                api_request.return_value.json.return_value = {"chat_id": "abc123"}
                result = CliRunner().invoke(chat_group, ["-m", "hello", "--image", str(image_path), "--topic", "dev"])

            self.assertEqual(result.exit_code, 0)
            api_request.assert_called_once()
            payload = api_request.call_args.kwargs["json"]
            self.assertEqual(payload["message"], "hello")
            self.assertEqual(payload["topic"], "dev")
            self.assertNotIn("image_uploads", payload)
            staged_path = Path(payload["images"][0])
            self.assertEqual(staged_path.parent, assets_dir.resolve())
            self.assertRegex(staged_path.name, r"cli-\d{8}T\d{6}\.\d{3}Z-photo-[0-9a-f]{8}\.jpg")
            self.assertEqual(staged_path.read_bytes(), b"jpg")

    def test_chat_message_reuses_existing_asset_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir) / "assets" / "images"
            assets_dir.mkdir(parents=True)
            image_path = assets_dir / "photo.jpg"
            image_path.write_bytes(b"jpg")

            with patch("yagent.util.images.IMAGE_ASSETS_DIR", assets_dir), \
                 patch("yagent.commands.chat.click.api_request") as api_request:
                api_request.return_value.json.return_value = {"chat_id": "abc123"}
                result = CliRunner().invoke(chat_group, ["-m", "hello", "--image", str(image_path)])

            self.assertEqual(result.exit_code, 0)
            payload = api_request.call_args.kwargs["json"]
            self.assertEqual(payload["images"], [str(image_path.resolve())])

    def test_chat_message_passes_remote_image_url_through(self):
        with patch("yagent.commands.chat.click.api_request") as api_request:
            api_request.return_value.json.return_value = {"chat_id": "abc123"}
            result = CliRunner().invoke(chat_group, ["-m", "hello", "--image", "https://example.com/photo.jpg", "--image", "https://example.com/other.png"])

        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["images"], ["https://example.com/photo.jpg", "https://example.com/other.png"])


if __name__ == "__main__":
    unittest.main()
