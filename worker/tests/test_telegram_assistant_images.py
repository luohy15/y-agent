import unittest
from unittest.mock import patch

from storage.entity.dto import Chat, Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import _consolidate_turn_images, _send_telegram_reply, message_callback


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


class ConsolidateTurnImagesTest(unittest.TestCase):
    def test_moves_images_to_result_message_and_clears_intermediate_chunks(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "", ["/tmp/a.png", "/tmp/dup.png"], message_id="a1"),
                _message("assistant", "done", ["/tmp/dup.png", "https://example.com/b.jpg"], message_id="a2"),
            ]
        )

        self.assertTrue(_consolidate_turn_images(chat))

        self.assertEqual(chat.messages[1].images, [])
        self.assertEqual(chat.messages[2].images, ["/tmp/a.png", "/tmp/dup.png", "https://example.com/b.jpg"])

    def test_ignores_images_from_previous_turns(self):
        chat = _chat(
            [
                _message("user", "old", message_id="u1"),
                _message("assistant", "old done", ["/tmp/old.png"], message_id="a1"),
                _message("user", "new", message_id="u2"),
                _message("assistant", "", ["/tmp/new.png"], message_id="a2"),
                _message("assistant", "new done", message_id="a3"),
            ]
        )

        self.assertTrue(_consolidate_turn_images(chat))

        self.assertEqual(chat.messages[1].images, ["/tmp/old.png"])
        self.assertEqual(chat.messages[3].images, [])
        self.assertEqual(chat.messages[4].images, ["/tmp/new.png"])

    def test_noops_when_images_are_already_on_result_message(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "done", ["/tmp/final.png"], message_id="a1"),
            ]
        )

        self.assertFalse(_consolidate_turn_images(chat))
        self.assertEqual(chat.messages[1].images, ["/tmp/final.png"])

    def test_empty_text_turn_falls_back_to_last_assistant_chunk(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "", ["/tmp/a.png"], message_id="a1"),
                _message("assistant", "", ["/tmp/b.png"], message_id="a2"),
            ]
        )

        self.assertTrue(_consolidate_turn_images(chat))

        self.assertEqual(chat.messages[1].images, [])
        self.assertEqual(chat.messages[2].images, ["/tmp/a.png", "/tmp/b.png"])


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

    def test_sends_images_from_result_message_only(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "", message_id="a1"),
                _message("assistant", "done", ["/tmp/attached-on-tool-turn.png", "https://example.com/final.jpg"], message_id="a2"),
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

    def test_image_only_turn_sends_photo_without_caption(self):
        chat = _chat(
            [
                _message("user", "make image", message_id="u1"),
                _message("assistant", "", ["/tmp/image-only.png"], message_id="a1"),
            ]
        )

        with (
            patch("worker.runner._resolve_telegram_target", return_value=("token", "tg-chat", 9)),
            patch("worker.runner._send_telegram_photo_reference") as send_photo,
            patch("storage.util.send_telegram_message") as send_message,
        ):
            _send_telegram_reply(chat, 1)

        send_message.assert_not_called()
        send_photo.assert_called_once_with("token", "tg-chat", "/tmp/image-only.png", caption=None, topic_id=9)

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
