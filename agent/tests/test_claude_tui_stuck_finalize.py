import asyncio
import json
import time
import unittest
from unittest.mock import Mock, patch

import agent.claude_tui as claude_tui
from agent.claude_tui import _footer_is_idle, tail_claude_tui_output


class FakeTuiClient:
    def __init__(self, lines=None, pane=""):
        self.lines = list(lines or [])
        self.pane = pane
        self.tail_calls = 0
        self.capture_calls = 0
        self.commands = []

    def exec_command(self, cmd):
        self.commands.append(cmd)
        return (Mock(), Mock(), Mock())

    def ssh_exec(self, _client, cmd):
        if cmd == "echo $HOME":
            return "/home/test\n"
        if cmd.startswith("tail -n +"):
            self.tail_calls += 1
            start = int(cmd.split("tail -n +", 1)[1].split(" ", 1)[0]) - 1
            selected = self.lines[start:]
            return ("\n".join(selected) + "\n") if selected else ""
        if cmd.startswith("tmux capture-pane"):
            self.capture_calls += 1
            return self.pane
        return ""


def _assistant_text_line(text="partial reply"):
    return json.dumps({
        "type": "assistant",
        "uuid": "assistant-1",
        "timestamp": "2026-06-15T00:00:00.000Z",
        "sessionId": "session-1",
        "cwd": "/work",
        "message": {
            "model": "claude-opus",
            "content": [{"type": "text", "text": text}],
        },
    })


class ClaudeTuiFooterIdleTest(unittest.TestCase):
    def test_footer_is_idle_requires_ready_footer_without_running_marker(self):
        self.assertTrue(_footer_is_idle("... bypass permissions on (shift+tab to cycle)"))
        self.assertFalse(_footer_is_idle(""))
        self.assertFalse(_footer_is_idle("... bypass permissions on · esc to interrupt"))


class ClaudeTuiStuckFinalizeTest(unittest.IsolatedAsyncioTestCase):
    async def _tail(self, fake, **kwargs):
        with (
            patch.object(claude_tui, "_ssh_exec", side_effect=fake.ssh_exec),
            patch.object(claude_tui, "_tmux_session_alive", return_value=True),
            patch.object(claude_tui, "POLL_INTERVAL_SECONDS", 0.001),
            patch.object(claude_tui, "IDLE_GUARD_SECONDS", 0.001),
            patch.object(claude_tui, "IDLE_FINALIZE_SECONDS", 0.005),
        ):
            return await tail_claude_tui_output(
                chat_id="chat-1",
                vm_config=Mock(work_dir="/work"),
                work_dir="/work",
                session_id="session-1",
                ssh_client=fake,
                **kwargs,
            )

    async def test_static_offset_idle_footer_errors_when_nothing_was_emitted(self):
        fake = FakeTuiClient(
            pane="Claude ready\nbypass permissions on (shift+tab to cycle)",
        )

        result = await self._tail(fake)

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["result_data"]["is_error"])
        self.assertIn("no turn_duration marker", result["result_data"]["result"])
        self.assertEqual(result["offset"], 0)
        self.assertTrue(any("kill-session" in cmd for cmd in fake.commands))

    async def test_static_offset_idle_footer_flushes_partial_content_as_completed(self):
        fake = FakeTuiClient(
            lines=[_assistant_text_line("partial answer")],
            pane="Claude ready\nbypass permissions on (shift+tab to cycle)",
        )
        emitted = []

        result = await self._tail(fake, message_callback=emitted.append)

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["result_data"]["is_error"])
        self.assertEqual(result["offset"], 1)
        self.assertEqual([m.content for m in emitted], ["partial answer"])
        self.assertTrue(any("kill-session" in cmd for cmd in fake.commands))

    async def test_static_offset_busy_footer_waits_until_deadline(self):
        fake = FakeTuiClient(
            pane="Claude running\nbypass permissions on (shift+tab to cycle) · esc to interrupt",
        )
        started = time.monotonic()

        result = await self._tail(
            fake,
            check_deadline_fn=lambda: time.monotonic() - started > 0.03,
        )

        self.assertFalse(result["is_done"])
        self.assertEqual(result["status"], "monitoring")
        self.assertGreater(fake.capture_calls, 0)
        self.assertFalse(any("kill-session" in cmd for cmd in fake.commands))


if __name__ == "__main__":
    unittest.main()
