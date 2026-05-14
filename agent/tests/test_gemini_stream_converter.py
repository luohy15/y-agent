import json
import unittest
import asyncio

from agent.gemini_cli import GeminiStreamConverter, tail_gemini_output


class _FakeChannel:
    def close(self):
        pass


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines
        self.channel = _FakeChannel()

    def __iter__(self):
        return iter(self._lines)


class _FakeSshClient:
    def __init__(self, lines):
        self._lines = lines

    def exec_command(self, _cmd):
        return None, _FakeStream(self._lines), _FakeStream([])


class GeminiStreamConverterTest(unittest.TestCase):
    def test_message_event_converts_assistant_text(self):
        converter = GeminiStreamConverter()
        converter.process_line(json.dumps({
            "type": "init",
            "session_id": "session-123",
            "model": "gemini-2.5-pro",
        }))

        messages = converter.process_line(json.dumps({
            "type": "message",
            "role": "assistant",
            "content": "Done.",
            "timestamp": "2026-05-14T10:00:00.000Z",
        }))

        self.assertEqual(converter.session_id, "session-123")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertEqual(messages[0].provider, "gemini_cli")
        self.assertEqual(messages[0].model, "gemini-2.5-pro")
        self.assertEqual(messages[0].content, "Done.")

    def test_tool_use_and_result_convert_to_tool_messages(self):
        converter = GeminiStreamConverter()

        started = converter.process_line(json.dumps({
            "type": "tool_use",
            "tool_name": "Bash",
            "tool_id": "bash-123",
            "parameters": {"command": "ls -la"},
        }))
        completed = converter.process_line(json.dumps({
            "type": "tool_result",
            "tool_id": "bash-123",
            "status": "success",
            "output": "file1\nfile2\n",
        }))

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].tool_calls[0]["id"], "bash-123")
        self.assertEqual(json.loads(started[0].tool_calls[0]["function"]["arguments"]), {
            "command": "ls -la",
        })
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].role, "tool")
        self.assertEqual(completed[0].tool, "Bash")
        self.assertEqual(completed[0].tool_call_id, "bash-123")
        self.assertEqual(completed[0].content, "file1\nfile2\n")
        self.assertEqual(completed[0].arguments, {"command": "ls -la"})

    def test_result_extracts_usage(self):
        converter = GeminiStreamConverter()

        converter.process_line(json.dumps({
            "type": "result",
            "session_id": "session-456",
            "status": "success",
            "stats": {
                "input_tokens": 10,
                "output_tokens": 20,
            },
        }))

        self.assertEqual(converter.session_id, "session-456")
        self.assertEqual(converter.usage, {
            "input_tokens": 10,
            "output_tokens": 20,
        })

    def test_warning_event_followed_by_success_is_not_fatal(self):
        lines = [
            json.dumps({"type": "init", "session_id": "session-789"}) + "\n",
            json.dumps({"type": "error", "message": "non-fatal warning"}) + "\n",
            json.dumps({
                "type": "result",
                "status": "success",
                "stats": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                },
            }) + "\n",
        ]

        result = asyncio.run(tail_gemini_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"], "session-789")
        self.assertEqual(result["result_data"]["usage"], {
            "input_tokens": 1,
            "output_tokens": 2,
        })


if __name__ == "__main__":
    unittest.main()
