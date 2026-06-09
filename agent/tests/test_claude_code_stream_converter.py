"""Unit tests for agent.claude_code.StreamConverter — the event->Message parser
for the DEFAULT backend.

codex/gemini/pi all have a stream-converter test; claude_code only had the
cancellation test. This mirrors test_codex_stream_converter.py: text extraction,
tool_use -> assistant tool_calls, tool_result -> tool Message, parent_id linking,
and the malformed-line tolerance.
"""

import json
import unittest

from agent.claude_code import StreamConverter


class ClaudeCodeStreamConverterTest(unittest.TestCase):
    def test_assistant_text_and_thinking(self):
        converter = StreamConverter()
        msgs = converter.process_line(json.dumps({
            "type": "assistant",
            "uuid": "u1",
            "message": {
                "model": "claude",
                "content": [
                    {"type": "thinking", "thinking": "let me think"},
                    {"type": "text", "text": "hello world"},
                ],
            },
        }))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "assistant")
        self.assertEqual(msgs[0].content, "hello world")
        self.assertEqual(msgs[0].reasoning_content, "let me think")
        self.assertEqual(msgs[0].id, "u1")
        self.assertEqual(msgs[0].provider, "claude_code")
        self.assertIsNone(msgs[0].tool_calls)

    def test_tool_use_becomes_assistant_tool_call(self):
        converter = StreamConverter()
        msgs = converter.process_line(json.dumps({
            "type": "assistant",
            "uuid": "u2",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                ],
            },
        }))
        self.assertEqual(len(msgs), 1)
        call = msgs[0].tool_calls[0]
        self.assertEqual(call["id"], "t1")
        self.assertEqual(call["function"]["name"], "Bash")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"command": "ls"})
        self.assertEqual(call["status"], "approved")

    def test_tool_result_resolves_name_and_args_from_index(self):
        converter = StreamConverter()
        # The tool_use must be seen first to populate the index.
        converter.process_line(json.dumps({
            "type": "assistant",
            "uuid": "u3",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t9", "name": "Read", "input": {"file_path": "/x"}},
                ],
            },
        }))
        msgs = converter.process_line(json.dumps({
            "type": "user",
            "uuid": "u4",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t9", "content": "file body"},
                ],
            },
        }))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "tool")
        self.assertEqual(msgs[0].tool, "Read")
        self.assertEqual(msgs[0].tool_call_id, "t9")
        self.assertEqual(msgs[0].arguments, {"file_path": "/x"})
        self.assertEqual(msgs[0].content, "file body")

    def test_tool_result_serializes_non_string_content(self):
        converter = StreamConverter()
        msgs = converter.process_line(json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "unknown", "content": [{"type": "text", "text": "x"}]},
                ],
            },
        }))
        self.assertEqual(msgs[0].content, json.dumps([{"type": "text", "text": "x"}]))
        # Unknown tool_use_id -> name/args left unresolved.
        self.assertIsNone(msgs[0].tool)

    def test_empty_assistant_message_dropped(self):
        converter = StreamConverter()
        self.assertEqual(converter.process_line(json.dumps({
            "type": "assistant",
            "message": {"content": []},
        })), [])

    def test_malformed_line_tolerated(self):
        converter = StreamConverter()
        self.assertEqual(converter.process_line("not json"), [])
        self.assertEqual(converter.process_line(""), [])

    def test_parent_id_links_across_lines(self):
        converter = StreamConverter(last_message_id="seed")
        first = converter.process_line(json.dumps({
            "type": "assistant", "uuid": "a1",
            "message": {"content": [{"type": "text", "text": "one"}]},
        }))
        second = converter.process_line(json.dumps({
            "type": "assistant", "uuid": "a2",
            "message": {"content": [{"type": "text", "text": "two"}]},
        }))
        self.assertEqual(first[0].parent_id, "seed")
        self.assertEqual(second[0].parent_id, "a1")


if __name__ == "__main__":
    unittest.main()
