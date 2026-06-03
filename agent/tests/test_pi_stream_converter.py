import json
import unittest
import asyncio

from agent.pi_cli import PiStreamConverter, tail_pi_output


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


class PiStreamConverterTest(unittest.TestCase):
    def test_session_event_sets_session_id(self):
        converter = PiStreamConverter()
        messages = converter.process_line(json.dumps({
            "type": "session",
            "version": 3,
            "id": "019e8cee-0801-79f5-9b4e-1585837677de",
            "cwd": "/repo",
        }))

        self.assertEqual(converter.session_id, "019e8cee-0801-79f5-9b4e-1585837677de")
        self.assertEqual(messages, [])

    def test_assistant_message_end_converts_text_only(self):
        converter = PiStreamConverter()
        messages = converter.process_line(json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "model": "gemini-2.5-flash",
                "content": [
                    {"type": "thinking", "thinking": "let me think"},
                    {"type": "text", "text": "Here are the files."},
                ],
                "usage": {"input": 100, "output": 20},
            },
        }))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertEqual(messages[0].provider, "pi_cli")
        self.assertEqual(messages[0].model, "gemini-2.5-flash")
        self.assertEqual(messages[0].content, "Here are the files.")
        self.assertEqual(converter.usage, {"input_tokens": 100, "output_tokens": 20})

    def test_user_message_end_is_ignored(self):
        converter = PiStreamConverter()
        messages = converter.process_line(json.dumps({
            "type": "message_end",
            "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        }))
        self.assertEqual(messages, [])

    def test_assistant_toolcall_only_message_emits_nothing(self):
        # A message_end whose only content is a toolCall (no text) yields no message;
        # the tool call itself arrives via tool_execution_start.
        converter = PiStreamConverter()
        messages = converter.process_line(json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "use bash"},
                    {"type": "toolCall", "id": "bash_1", "name": "bash", "arguments": {"command": "ls"}},
                ],
                "usage": {"input": 50, "output": 5},
            },
        }))
        self.assertEqual(messages, [])
        # usage still accumulates from the message
        self.assertEqual(converter.usage, {"input_tokens": 50, "output_tokens": 5})

    def test_tool_execution_start_and_end_convert_to_tool_messages(self):
        converter = PiStreamConverter()

        started = converter.process_line(json.dumps({
            "type": "tool_execution_start",
            "toolCallId": "bash_1780480872760_1",
            "toolName": "bash",
            "args": {"command": "ls -F"},
        }))
        completed = converter.process_line(json.dumps({
            "type": "tool_execution_end",
            "toolCallId": "bash_1780480872760_1",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "README.md\na.txt\n"}]},
            "isError": False,
        }))

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].tool_calls[0]["id"], "bash_1780480872760_1")
        self.assertEqual(json.loads(started[0].tool_calls[0]["function"]["arguments"]), {
            "command": "ls -F",
        })
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].role, "tool")
        self.assertEqual(completed[0].tool, "bash")
        self.assertEqual(completed[0].tool_call_id, "bash_1780480872760_1")
        self.assertEqual(completed[0].content, "README.md\na.txt\n")
        self.assertEqual(completed[0].arguments, {"command": "ls -F"})

    def test_tool_error_appends_marker(self):
        converter = PiStreamConverter()
        converter.process_line(json.dumps({
            "type": "tool_execution_start",
            "toolCallId": "bash_2",
            "toolName": "bash",
            "args": {"command": "false"},
        }))
        completed = converter.process_line(json.dumps({
            "type": "tool_execution_end",
            "toolCallId": "bash_2",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "boom"}]},
            "isError": True,
        }))
        self.assertIn("[pi tool error]", completed[0].content)
        self.assertIn("boom", completed[0].content)

    def test_output_tokens_sum_input_tokens_last_wins(self):
        converter = PiStreamConverter()
        for inp, out in ((100, 10), (200, 15)):
            converter.process_line(json.dumps({
                "type": "message_end",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "x"}],
                            "usage": {"input": inp, "output": out}},
            }))
        self.assertEqual(converter.usage, {"input_tokens": 200, "output_tokens": 25})

    def test_full_stream_completes_with_usage(self):
        lines = [
            json.dumps({"type": "session", "id": "sess-1", "cwd": "/repo"}) + "\n",
            json.dumps({"type": "agent_start"}) + "\n",
            json.dumps({
                "type": "message_end",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                            "usage": {"input": 7, "output": 2}},
            }) + "\n",
            json.dumps({"type": "agent_end", "messages": []}) + "\n",
        ]

        result = asyncio.run(tail_pi_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"], "sess-1")
        self.assertEqual(result["result_data"]["usage"], {
            "input_tokens": 7,
            "output_tokens": 2,
        })

    def test_exit_without_agent_end_is_error(self):
        lines = [
            json.dumps({"type": "session", "id": "sess-2", "cwd": "/repo"}) + "\n",
            json.dumps({
                "type": "message_end",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "partial"}]},
            }) + "\n",
        ]

        result = asyncio.run(tail_pi_output(
            chat_id="chat-2",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["result_data"]["is_error"])


if __name__ == "__main__":
    unittest.main()
