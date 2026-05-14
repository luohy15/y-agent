import json
import unittest

from agent.codex import CodexStreamConverter


class CodexStreamConverterTest(unittest.TestCase):
    def test_command_execution_uses_aggregated_output(self):
        converter = CodexStreamConverter()

        started = converter.process_line(json.dumps({
            "type": "item.started",
            "item": {
                "id": "item_0",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo steer-received'",
            },
        }))
        completed = converter.process_line(json.dumps({
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo steer-received'",
                "aggregated_output": "steer-received\n",
                "exit_code": 0,
                "status": "completed",
            },
        }))

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].tool_calls[0]["id"], "item_0")
        self.assertEqual(json.loads(started[0].tool_calls[0]["function"]["arguments"]), {
            "command": "echo steer-received",
        })
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].role, "tool")
        self.assertEqual(completed[0].tool, "Bash")
        self.assertEqual(completed[0].tool_call_id, "item_0")
        self.assertEqual(completed[0].content, "steer-received\n")
        self.assertEqual(completed[0].arguments, {"command": "echo steer-received"})

    def test_command_execution_serializes_non_string_output_fallback(self):
        converter = CodexStreamConverter()

        messages = converter.process_line(json.dumps({
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "status",
                "output": {"ok": True},
            },
        }))

        self.assertEqual(messages[0].content, '{"ok": true}')

    def test_file_change_uses_changes_metadata(self):
        converter = CodexStreamConverter()

        started = converter.process_line(json.dumps({
            "type": "item.started",
            "item": {
                "id": "item_11",
                "type": "file_change",
            },
        }))
        completed = converter.process_line(json.dumps({
            "type": "item.completed",
            "item": {
                "id": "item_11",
                "type": "file_change",
                "changes": [
                    {
                        "path": "/Users/roy/luohy15/code/y-agent-chat-backend-defaults-2079/web/src/App.tsx",
                        "kind": "update",
                    }
                ],
                "status": "completed",
            },
        }))

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].tool_calls[0]["id"], "item_11")
        self.assertEqual(json.loads(started[0].tool_calls[0]["function"]["arguments"]), {
            "file_path": "",
        })
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].tool, "Edit")
        self.assertEqual(completed[0].tool_call_id, "item_11")
        self.assertEqual(completed[0].arguments, {
            "file_path": "/Users/roy/luohy15/code/y-agent-chat-backend-defaults-2079/web/src/App.tsx",
            "path": "/Users/roy/luohy15/code/y-agent-chat-backend-defaults-2079/web/src/App.tsx",
            "changes": [
                {
                    "path": "/Users/roy/luohy15/code/y-agent-chat-backend-defaults-2079/web/src/App.tsx",
                    "kind": "update",
                }
            ],
        })
        self.assertEqual(
            completed[0].content,
            "update /Users/roy/luohy15/code/y-agent-chat-backend-defaults-2079/web/src/App.tsx",
        )


if __name__ == "__main__":
    unittest.main()
