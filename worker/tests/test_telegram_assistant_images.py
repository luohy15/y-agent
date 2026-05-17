import unittest
from unittest.mock import patch

from storage.entity.dto import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _send_telegram_reply, message_callback


def _message(role="assistant", content="hello", images=None, message_id="m1"):
    return Message(
        id=message_id,
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        images=images,
    )


def _chat(messages):
    if not isinstance(messages, list):
        messages = [messages]
    return Chat(id="chat-1", create_time="", update_time="", topic="dev", messages=messages)


class AssistantImageAttachTest(unittest.TestCase):
    def test_message_callback_does_not_extract_images_from_text(self):
        message = _message(
            content="created /Users/roy/luohy15/assets/images/not-attached.png",
            images=["https://example.com/explicit.jpg"],
        )

        with patch("worker.runner.chat_service.append_message_sync") as append_message:
            message_callback("chat-1", message)

        append_message.assert_called_once_with("chat-1", message)
        self.assertEqual(message.images, ["https://example.com/explicit.jpg"])


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

    def test_aggregates_images_across_assistant_messages_in_current_turn(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "", ["/tmp/attached-on-tool-turn.png"], message_id="a1"),
                _message("assistant", "done", ["https://example.com/final.jpg"], message_id="a2"),
            ]
        )

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", 7)),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_reply(chat, 1)

        send_message.assert_not_called()
        self.assertEqual(send_photo.call_count, 2)
        self.assertEqual(send_photo.call_args_list[0].args, ("token", "tg-chat", "/tmp/attached-on-tool-turn.png"))
        self.assertEqual(send_photo.call_args_list[0].kwargs, {"caption": "done", "topic_id": 7})
        self.assertEqual(send_photo.call_args_list[1].args, ("token", "tg-chat", "https://example.com/final.jpg"))
        self.assertEqual(send_photo.call_args_list[1].kwargs, {"caption": None, "topic_id": 7})

    def test_ignores_images_from_previous_turns(self):
        chat = _chat(
            [
                _message("user", "old", message_id="u1"),
                _message("assistant", "old done", ["/tmp/old.png"], message_id="a1"),
                _message("user", "new", message_id="u2"),
                _message("assistant", "new done", message_id="a2"),
            ]
        )

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", None)),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_reply(chat, 1)

        send_photo.assert_not_called()
        send_message.assert_called_once_with("token", "tg-chat", "new done", None)


if __name__ == "__main__":
    unittest.main()
