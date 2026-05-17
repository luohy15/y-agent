import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.chat.click import chat_group


class ChatAttachImageCliTest(unittest.TestCase):
    def test_attach_uploads_local_image_content(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.png"
            image_path.write_bytes(b"png")

            with patch("yagent.commands.chat.attach.api_request") as api_request:
                api_request.return_value.json.return_value = {"count": 1}
                result = CliRunner().invoke(chat_group, ["attach", "--chat-id", "abc123", "--image", str(image_path)])

        self.assertEqual(result.exit_code, 0)
        api_request.assert_called_once()
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "abc123")
        self.assertNotIn("images", payload)
        self.assertEqual(payload["image_uploads"], [{"filename": "photo.png", "content_base64": base64.b64encode(b"png").decode("ascii")}])

    def test_attach_passes_remote_image_refs_through(self):
        with patch("yagent.commands.chat.attach.api_request") as api_request:
            api_request.return_value.json.return_value = {"count": 2}
            result = CliRunner().invoke(
                chat_group,
                [
                    "attach",
                    "--chat-id",
                    "abc123",
                    "--image",
                    "https://example.com/photo.jpg",
                    "--image",
                    "s3://bucket/images/photo.png",
                ],
            )

        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["images"], ["https://example.com/photo.jpg", "s3://bucket/images/photo.png"])
        self.assertNotIn("image_uploads", payload)


if __name__ == "__main__":
    unittest.main()
