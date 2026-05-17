import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from storage.util import send_telegram_photo


class TelegramPhotoUtilTest(unittest.TestCase):
    def test_send_photo_accepts_http_url(self):
        response = SimpleNamespace(is_success=True, raise_for_status=lambda: None)
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = None
        client.post.return_value = response

        with patch("httpx.Client", return_value=client):
            send_telegram_photo("token", "chat", "https://example.com/photo.jpg", caption="hello", message_thread_id=7)

        client.post.assert_called_once_with(
            "https://api.telegram.org/bottoken/sendPhoto",
            data={
                "chat_id": "chat",
                "caption": "hello",
                "parse_mode": "HTML",
                "message_thread_id": 7,
                "photo": "https://example.com/photo.jpg",
            },
        )


if __name__ == "__main__":
    unittest.main()
