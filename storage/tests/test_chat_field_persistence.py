import unittest
from types import SimpleNamespace

from storage.repository.chat import _resolve_immutable_field, _resolve_routing_field


def _pair(entity_val, chat_val):
    return SimpleNamespace(f=entity_val), SimpleNamespace(f=chat_val, id="chat-1")


class ImmutableFieldTest(unittest.TestCase):
    def test_first_assignment_takes_the_dto_value(self):
        entity, chat = _pair(None, "claude_code")
        self.assertEqual(_resolve_immutable_field(entity, chat, "f"), "claude_code")

    def test_change_is_refused_once_set(self):
        entity, chat = _pair("claude_code", "perplexity")
        self.assertEqual(_resolve_immutable_field(entity, chat, "f"), "claude_code")


class RoutingFieldTest(unittest.TestCase):
    """bot_name / tier move with an accepted re-bot; backend does not."""

    def test_first_assignment_takes_the_dto_value(self):
        entity, chat = _pair(None, "sonnet")
        self.assertEqual(_resolve_routing_field(entity, chat, "f"), "sonnet")

    def test_change_is_persisted_once_set(self):
        entity, chat = _pair("sonnet", "opus")
        self.assertEqual(_resolve_routing_field(entity, chat, "f"), "opus")

    def test_unset_dto_value_never_clears_the_persisted_one(self):
        for empty in (None, ""):
            with self.subTest(empty=empty):
                entity, chat = _pair("sonnet", empty)
                self.assertEqual(_resolve_routing_field(entity, chat, "f"), "sonnet")


if __name__ == "__main__":
    unittest.main()
