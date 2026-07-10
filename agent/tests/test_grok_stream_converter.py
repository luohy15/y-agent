import json
import unittest
import asyncio

from agent.grok_build import GrokStreamConverter, tail_grok_output


class _FakeChannel:
    def close(self):
        pass

    def recv_exit_status(self):
        return 0


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines
        self.channel = _FakeChannel()

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return "".join(self._lines).encode()


class _FakeSshClient:
    """Fake SSH client: streams `lines` for the tail command, reports the
    tmux session as dead for the liveness-check fallback (`_tmux_session_alive`)."""

    def __init__(self, lines):
        self._lines = lines

    def exec_command(self, cmd):
        if "has-session" in cmd:
            return None, _FakeStream(["dead\n"]), _FakeStream([])
        return None, _FakeStream(self._lines), _FakeStream([])


class GrokStreamConverterTest(unittest.TestCase):
    def test_text_deltas_flush_as_single_assistant_message_on_end(self):
        converter = GrokStreamConverter()

        self.assertEqual(converter.process_line(json.dumps({"type": "text", "data": "Here's"})), [])
        self.assertEqual(converter.process_line(json.dumps({"type": "text", "data": " a summary"})), [])

        messages = converter.process_line(json.dumps({
            "type": "end",
            "stopReason": "EndTurn",
            "sessionId": "abc123",
            "requestId": "xyz789",
        }))

        self.assertEqual(converter.session_id, "abc123")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertEqual(messages[0].provider, "grok_build")
        self.assertEqual(messages[0].content, "Here's a summary")

    def test_text_across_invisible_tool_call_gets_separator(self):
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "text", "data": "I'll read the file."}))
        converter.process_line(json.dumps({"type": "thought", "data": "The file contains a marker."}))
        converter.process_line(json.dumps({"type": "text", "data": "`notes.txt` contains: X."}))

        messages = converter.process_line(json.dumps({"type": "end", "sessionId": "abc123"}))

        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0].content,
            "I'll read the file.\n\n`notes.txt` contains: X.",
        )

    def test_thought_deltas_become_reasoning_content(self):
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "thought", "data": "Analyzing the "}))
        converter.process_line(json.dumps({"type": "thought", "data": "directory structure..."}))
        converter.process_line(json.dumps({"type": "text", "data": "Done."}))

        messages = converter.process_line(json.dumps({
            "type": "end",
            "stopReason": "EndTurn",
            "sessionId": "abc123",
        }))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "Done.")
        self.assertEqual(messages[0].reasoning_content, "Analyzing the directory structure...")

    def test_error_event_flushes_partial_text_and_logs(self):
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "text", "data": "partial"}))
        messages = converter.process_line(json.dumps({
            "type": "error",
            "message": "Couldn't start session: boom",
        }))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "partial")

    def test_unknown_event_type_is_ignored_not_fatal(self):
        converter = GrokStreamConverter()
        messages = converter.process_line(json.dumps({"type": "tool_call", "name": "Bash"}))
        self.assertEqual(messages, [])

    def test_successful_run_via_tail(self):
        lines = [
            json.dumps({"type": "text", "data": "pong"}) + "\n",
            json.dumps({
                "type": "end",
                "stopReason": "EndTurn",
                "sessionId": "session-789",
                "requestId": "req-1",
            }) + "\n",
        ]

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"], "session-789")

    def test_error_only_run_via_tail_is_error_status(self):
        lines = [
            json.dumps({
                "type": "error",
                "message": "Couldn't set model 'grok-4.5': Invalid params: \"unknown model id\".",
            }) + "\n",
        ]

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown model id", result["result_data"]["result"])


if __name__ == "__main__":
    unittest.main()
