import unittest
from types import SimpleNamespace
from unittest.mock import patch

from storage.entity.dto import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _send_telegram_user_message, _telegram_photo_reference


def _message(content="hello", images=None, source=None):
    return Message(
        id="m1",
        role="user",
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        images=images,
        source=source,
    )


def _chat(message):
    return Chat(id="chat-1", create_time="", update_time="", topic="dev", messages=[message])


class TelegramUserImagesTest(unittest.TestCase):
    def test_luohy15_s3_reference_rewrites_to_cdn_url(self):
        self.assertEqual(
            _telegram_photo_reference("s3://luohy15/path with space/photo.jpg"),
            "https://cdn.luohy15.com/path%20with%20space/photo.jpg",
        )

    def test_user_images_are_sent_as_photos_with_caption_on_first(self):
        chat = _chat(_message("look", ["/tmp/a.jpg", "https://example.com/b.jpg"]))
        user = SimpleNamespace(username="roy", email="roy@example.com")

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", 42)),
            patch("storage.repository.user.get_user_by_id", return_value=user),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_user_message(chat, 1)

        send_message.assert_not_called()
        self.assertEqual(send_photo.call_count, 2)
        self.assertEqual(send_photo.call_args_list[0].args, ("token", "tg-chat", "/tmp/a.jpg"))
        self.assertEqual(send_photo.call_args_list[0].kwargs, {"caption": "roy: look", "topic_id": 42})
        self.assertEqual(send_photo.call_args_list[1].args, ("token", "tg-chat", "https://example.com/b.jpg"))
        self.assertEqual(send_photo.call_args_list[1].kwargs, {"caption": None, "topic_id": 42})

    def test_text_only_keeps_existing_message_send(self):
        chat = _chat(_message("hello"))
        user = SimpleNamespace(username="roy", email="roy@example.com")

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", None)),
            patch("storage.repository.user.get_user_by_id", return_value=user),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_user_message(chat, 1)

        send_photo.assert_not_called()
        send_message.assert_called_once_with("token", "tg-chat", "roy: hello", None)


if __name__ == "__main__":
    unittest.main()
