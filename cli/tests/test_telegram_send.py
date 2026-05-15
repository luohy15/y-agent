import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.telegram.send import telegram_send


class TelegramSendCliTest(unittest.TestCase):
    def test_sends_text_payload(self):
        with patch("yagent.commands.telegram.send.api_request") as api_request:
            result = CliRunner().invoke(telegram_send, ["--message", "hello"])

        self.assertEqual(result.exit_code, 0)
        api_request.assert_called_once_with("POST", "/api/telegram/send", json={"text": "hello"})

    def test_sends_image_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"jpg")
            assets_dir = Path(tmp_dir) / "assets" / "images"
            with patch("yagent.commands.telegram.send.IMAGE_ASSETS_DIR", assets_dir):
                with patch("yagent.commands.telegram.send.api_request") as api_request:
                    result = CliRunner().invoke(telegram_send, ["--image", str(image_path)])

            self.assertEqual(result.exit_code, 0)
            api_request.assert_called_once()
            self.assertEqual(api_request.call_args.kwargs["json"]["text"], "")
            staged_path = Path(api_request.call_args.kwargs["json"]["images"][0])
            self.assertEqual(staged_path.parent, assets_dir.resolve())
            self.assertEqual(staged_path.read_bytes(), b"jpg")


    def test_requires_message_or_image(self):
        result = CliRunner().invoke(telegram_send, [])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Provide --message and/or --image", result.output)


if __name__ == "__main__":
    unittest.main()
