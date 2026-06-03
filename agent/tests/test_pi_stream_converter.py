import json
import unittest
import asyncio

from agent.pi_cli import PiStreamConverter, tail_pi_output, _write_pi_models_json


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


class _ExecStream:
    def __init__(self, data=b"", exit_status=0):
        self._data = data
        self.channel = type("_Ch", (), {"recv_exit_status": staticmethod(lambda: exit_status)})()

    def read(self):
        return self._data


class _SftpFile:
    def __init__(self, sink, path):
        self._sink = sink
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, content):
        self._sink[self._path] = content


class _FakeSftp:
    def __init__(self, sink):
        self._sink = sink

    def open(self, path, _mode):
        return _SftpFile(self._sink, path)

    def close(self):
        pass


class _ModelsJsonClient:
    """Fake SSH client for _write_pi_models_json: serves $HOME + existing file.

    Emulates real exit codes so the missing-file path is faithful: `existing=None`
    means the file is absent, so a bare `cat` exits non-zero (which _ssh_exec
    raises on) unless the command guards it with `|| true`.
    """

    def __init__(self, home="/home/roy", existing=""):
        self.home = home
        self.existing = existing
        self.writes = {}
        self.commands = []

    def exec_command(self, cmd):
        self.commands.append(cmd)
        exit_status = 0
        if "$HOME" in cmd:
            data = self.home.encode()
        elif cmd.startswith("cat "):
            if self.existing is None:
                data = b""
                if "|| true" not in cmd:
                    exit_status = 1  # missing file: cat fails unless guarded
            else:
                data = self.existing.encode()
        else:  # mkdir -p / chmod
            data = b""
        return None, _ExecStream(data, exit_status), _ExecStream(b"")

    def open_sftp(self):
        return _FakeSftp(self.writes)


class WritePiModelsJsonTest(unittest.TestCase):
    PROVIDER = {"y-pi": {"baseUrl": "https://gw/openrouter", "api": "anthropic-messages",
                          "apiKey": "sk-or-x", "models": [{"id": "anthropic/claude-sonnet-4.6"}]}}

    def test_writes_provider_to_home_path(self):
        client = _ModelsJsonClient(home="/home/roy")
        _write_pi_models_json(client, self.PROVIDER)

        self.assertIn("/home/roy/.pi/agent/models.json", client.writes)
        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        self.assertEqual(written["providers"]["y-pi"]["baseUrl"], "https://gw/openrouter")

    def test_merges_into_existing_providers(self):
        existing = json.dumps({"providers": {"ollama": {"baseUrl": "http://localhost:11434/v1"}}})
        client = _ModelsJsonClient(existing=existing)
        _write_pi_models_json(client, self.PROVIDER)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        self.assertIn("ollama", written["providers"])
        self.assertIn("y-pi", written["providers"])

    def test_unparseable_existing_is_reset(self):
        client = _ModelsJsonClient(existing="{ not json")
        _write_pi_models_json(client, self.PROVIDER)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        self.assertEqual(list(written["providers"]), ["y-pi"])

    def test_missing_file_does_not_raise(self):
        # A host with no ~/.pi/agent/models.json: cat exits non-zero, so the read
        # must be guarded (`|| true`) or _ssh_exec raises before the write.
        client = _ModelsJsonClient(existing=None)
        _write_pi_models_json(client, self.PROVIDER)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        self.assertEqual(list(written["providers"]), ["y-pi"])

    def test_models_json_is_chmod_600(self):
        client = _ModelsJsonClient(existing=None)
        _write_pi_models_json(client, self.PROVIDER)

        self.assertTrue(
            any("chmod 600" in c and "models.json" in c for c in client.commands)
        )


if __name__ == "__main__":
    unittest.main()
