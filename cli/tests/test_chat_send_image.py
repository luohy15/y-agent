import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.chat.click import chat_group


class ChatSendImageCliTest(unittest.TestCase):
    def test_chat_message_sends_image_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"jpg")

            with patch("yagent.commands.chat.click.api_request") as api_request:
                api_request.return_value.json.return_value = {"chat_id": "abc123"}
                result = CliRunner().invoke(chat_group, ["-m", "hello", "--image", str(image_path), "--topic", "dev"])

            self.assertEqual(result.exit_code, 0)
            api_request.assert_called_once()
            payload = api_request.call_args.kwargs["json"]
            self.assertEqual(payload["message"], "hello")
            self.assertEqual(payload["topic"], "dev")
            upload = payload["image_uploads"][0]
            self.assertEqual(upload["filename"], "photo.jpg")
            self.assertEqual(base64.b64decode(upload["content_base64"]), b"jpg")


if __name__ == "__main__":
    unittest.main()
