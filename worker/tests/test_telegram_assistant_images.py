import unittest
from unittest.mock import patch

from storage.entity.dto import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _extract_assistant_images, _send_telegram_reply, message_callback


def _message(role="assistant", content="hello", images=None):
    return Message(
        id="m1",
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        images=images,
    )


def _chat(message):
    return Chat(id="chat-1", create_time="", update_time="", topic="dev", messages=[message])


class AssistantImageExtractionTest(unittest.TestCase):
    def test_extracts_supported_images_and_ignores_unsupported_references(self):
        content = "\n".join(
            [
                "local /Users/roy/luohy15/assets/images/generated.png",
                "url https://example.com/rendered.PNG",
                "s3 s3://bucket/path/image.webp",
                "ignore /tmp/not-owned.jpg",
                "ignore /Users/roy/luohy15/assets/images/readme.txt",
            ]
        )

        self.assertEqual(
            _extract_assistant_images(content),
            [
                "/Users/roy/luohy15/assets/images/generated.png",
                "https://example.com/rendered.PNG",
                "s3://bucket/path/image.webp",
            ],
        )

    def test_deduplicates_in_order_and_trims_trailing_punctuation(self):
        content = (
            "![a](/Users/roy/luohy15/assets/images/a.png). "
            "again /Users/roy/luohy15/assets/images/a.png, "
            "then `https://example.com/b.jpg` "
            "and s3://bucket/c.gif)."
        )

        self.assertEqual(
            _extract_assistant_images(content),
            [
                "/Users/roy/luohy15/assets/images/a.png",
                "https://example.com/b.jpg",
                "s3://bucket/c.gif",
            ],
        )

    def test_message_callback_merges_extracted_images_before_persisting(self):
        message = _message(
            content="created /Users/roy/luohy15/assets/images/new.png",
            images=["https://example.com/existing.jpg"],
        )

        with patch("worker.runner.chat_service.append_message_sync") as append_message:
            message_callback("chat-1", message)

        append_message.assert_called_once_with("chat-1", message)
        self.assertEqual(
            message.images,
            ["https://example.com/existing.jpg", "/Users/roy/luohy15/assets/images/new.png"],
        )


class TelegramAssistantImagesTest(unittest.TestCase):
    def test_assistant_images_are_sent_as_photos_with_caption_on_first(self):
        chat = _chat(_message("assistant", "done", ["/tmp/a.jpg", "https://example.com/b.jpg"]))

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", 42)),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_reply(chat, 1)

        send_message.assert_not_called()
        self.assertEqual(send_photo.call_count, 2)
        self.assertEqual(send_photo.call_args_list[0].args, ("token", "tg-chat", "/tmp/a.jpg"))
        self.assertEqual(send_photo.call_args_list[0].kwargs, {"caption": "done", "topic_id": 42})
        self.assertEqual(send_photo.call_args_list[1].args, ("token", "tg-chat", "https://example.com/b.jpg"))
        self.assertEqual(send_photo.call_args_list[1].kwargs, {"caption": None, "topic_id": 42})

    def test_text_only_keeps_existing_message_send(self):
        chat = _chat(_message("assistant", "hello"))

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", None)),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_reply(chat, 1)

        send_photo.assert_not_called()
        send_message.assert_called_once_with("token", "tg-chat", "hello", None)


if __name__ == "__main__":
    unittest.main()
