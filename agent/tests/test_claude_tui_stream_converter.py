"""Unit tests for agent.claude_tui.ClaudeTuiStreamConverter (sub-task 2).

The TUI backend reads the Claude Code history JSONL (one content block per
line), so consecutive assistant records must merge into a single Message. This
test feeds a recorded multi-line assistant + tool_use/tool_result transcript and
asserts:
  - the merged assistant Message + tool Message are produced,
  - parent_ids link sequentially,
  - the streamed output is identical to convert_history_session on the same
    assistant + tool_result input (the DRY safety net for the copied accumulator).
"""

import json
import unittest

from agent.claude_tui import ClaudeTuiStreamConverter
from agent.claude_code import convert_history_session


# A two-block assistant turn (thinking + tool_use), a tool_result, then a final
# two-block assistant turn (thinking + text). Each line carries exactly one
# content block, mirroring the real history JSONL layout.
_LINES = [
    json.dumps({
        "type": "assistant", "uuid": "a1", "timestamp": "2026-06-15T00:00:01.000Z",
        "sessionId": "sess-1", "cwd": "/home/roy/x",
        "message": {"model": "claude-opus", "content": [
            {"type": "thinking", "thinking": "let me look"},
        ]},
    }),
    json.dumps({
        "type": "assistant", "uuid": "a1", "timestamp": "2026-06-15T00:00:01.500Z",
        "sessionId": "sess-1", "cwd": "/home/roy/x",
        "message": {"model": "claude-opus", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
        ]},
    }),
    json.dumps({
        "type": "user", "uuid": "u1", "timestamp": "2026-06-15T00:00:02.000Z",
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "file-a\nfile-b"},
        ]},
    }),
    json.dumps({
        "type": "assistant", "uuid": "a2", "timestamp": "2026-06-15T00:00:03.000Z",
        "sessionId": "sess-1", "cwd": "/home/roy/x",
        "message": {"model": "claude-opus", "content": [
            {"type": "thinking", "thinking": "done"},
        ]},
    }),
    json.dumps({
        "type": "assistant", "uuid": "a2", "timestamp": "2026-06-15T00:00:03.500Z",
        "sessionId": "sess-1", "cwd": "/home/roy/x",
        "message": {"model": "claude-opus", "content": [
            {"type": "text", "text": "here are the files"},
        ]},
    }),
]

_FIELDS = (
    "role", "content", "reasoning_content", "id", "parent_id", "model",
    "provider", "tool", "arguments", "tool_call_id", "timestamp", "unix_timestamp",
)


def _stream(lines):
    converter = ClaudeTuiStreamConverter()
    out = []
    for line in lines:
        out.extend(converter.process_line(line))
    out.extend(converter.flush())
    return out, converter


def _snapshot(msg):
    return {f: getattr(msg, f, None) for f in _FIELDS}


def _tool_calls(msg):
    return msg.tool_calls


class ClaudeTuiStreamConverterTest(unittest.TestCase):
    def test_merges_consecutive_assistant_blocks(self):
        msgs, _ = _stream(_LINES)
        # assistant(thinking+tool_use), tool(result), assistant(thinking+text)
        self.assertEqual(len(msgs), 3)

        first = msgs[0]
        self.assertEqual(first.role, "assistant")
        self.assertEqual(first.reasoning_content, "let me look")
        self.assertEqual(first.id, "a1")
        self.assertEqual(len(first.tool_calls), 1)
        self.assertEqual(first.tool_calls[0]["function"]["name"], "Bash")

        tool = msgs[1]
        self.assertEqual(tool.role, "tool")
        self.assertEqual(tool.tool, "Bash")
        self.assertEqual(tool.tool_call_id, "t1")
        self.assertEqual(tool.arguments, {"command": "ls"})
        self.assertEqual(tool.content, "file-a\nfile-b")

        final = msgs[2]
        self.assertEqual(final.role, "assistant")
        self.assertEqual(final.content, "here are the files")
        self.assertEqual(final.reasoning_content, "done")

    def test_parent_ids_link_sequentially(self):
        msgs, _ = _stream(_LINES)
        self.assertIsNone(msgs[0].parent_id)
        self.assertEqual(msgs[1].parent_id, msgs[0].id)
        self.assertEqual(msgs[2].parent_id, msgs[1].id)

    def test_identical_to_convert_history_session(self):
        streamed, _ = _stream(_LINES)
        batch, _sid, _wd = convert_history_session(_LINES)

        self.assertEqual([_snapshot(m) for m in streamed], [_snapshot(m) for m in batch])
        self.assertEqual([_tool_calls(m) for m in streamed], [_tool_calls(m) for m in batch])

    def test_session_id_and_work_dir_captured(self):
        _, converter = _stream(_LINES)
        self.assertEqual(converter.session_id, "sess-1")
        self.assertEqual(converter.work_dir, "/home/roy/x")

    def test_standalone_user_text_dropped(self):
        """The live converter skips standalone user text (already in chat.messages),
        unlike convert_history_session which emits it for full-history import."""
        converter = ClaudeTuiStreamConverter()
        out = converter.process_line(json.dumps({
            "type": "user", "uuid": "u9", "timestamp": "2026-06-15T00:00:00.000Z",
            "message": {"content": "this is my prompt"},
        }))
        out.extend(converter.flush())
        self.assertEqual(out, [])

    def test_turn_duration_skipped_by_converter(self):
        converter = ClaudeTuiStreamConverter()
        self.assertEqual(converter.process_line(json.dumps({
            "type": "system", "subtype": "turn_duration", "durationMs": 1234,
        })), [])

    def test_has_pending_high_water_mark(self):
        converter = ClaudeTuiStreamConverter()
        converter.process_line(_LINES[0])  # assistant thinking
        self.assertTrue(converter.has_pending)
        converter.process_line(_LINES[1])  # assistant tool_use
        self.assertTrue(converter.has_pending)
        converter.process_line(_LINES[2])  # user tool_result -> flush
        self.assertFalse(converter.has_pending)

    def test_usage_accumulated_last_wins(self):
        converter = ClaudeTuiStreamConverter()
        converter.process_line(json.dumps({
            "type": "assistant", "uuid": "a1",
            "message": {"content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": 100, "output_tokens": 5}},
        }))
        converter.process_line(json.dumps({
            "type": "assistant", "uuid": "a2",
            "message": {"content": [{"type": "text", "text": "y"}],
                        "usage": {"input_tokens": 120, "output_tokens": 12,
                                  "cache_read_input_tokens": 80}},
        }))
        self.assertEqual(converter.usage["input_tokens"], 120)
        self.assertEqual(converter.usage["output_tokens"], 12)
        self.assertEqual(converter.usage["cache_read_input_tokens"], 80)


if __name__ == "__main__":
    unittest.main()
