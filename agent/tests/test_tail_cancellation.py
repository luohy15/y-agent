import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from agent.claude_code import tail_ssh_output
from agent.codex import tail_codex_output
from agent.gemini_cli import tail_gemini_output
from agent.pi_cli import tail_pi_output


class BlockingStdout:
    def __init__(self, lines):
        self._lines = list(lines)
        self._closed = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        if self._lines:
            return self._lines.pop(0)
        while not self._closed:
            pass
        raise EOFError()

    def close(self):
        self._closed = True


class TailCancellationTest(unittest.IsolatedAsyncioTestCase):
    async def _assert_cancel_returns_offset(self, tail_fn, line, expected_session_key, expected_session_value):
        stdout = BlockingStdout([line])
        client = Mock()
        client.exec_command.return_value = (Mock(), stdout, Mock())

        with patch("agent.poll_loop.PollLoop.stop") as poll_stop:
            task = asyncio.create_task(tail_fn(
                chat_id="chat-1",
                vm_config=Mock(),
                offset=10,
                last_message_id="msg-old",
                message_callback=lambda msg: None,
                ssh_client=client,
            ))
            await asyncio.sleep(0.05)
            task.cancel()
            result = await task

        self.assertEqual(result["offset"], 11)
        self.assertFalse(result["is_done"])
        self.assertEqual(result["status"], "monitoring")
        self.assertEqual(result.get(expected_session_key), expected_session_value)
        poll_stop.assert_called_once()

    async def test_cancelled_claude_tail_returns_latest_offset(self):
        line = json.dumps({"type": "system", "session_id": "claude-session"}) + "\n"
        await self._assert_cancel_returns_offset(
            tail_ssh_output,
            line,
            "session_id",
            "claude-session",
        )

    async def test_cancelled_codex_tail_returns_latest_offset(self):
        line = json.dumps({"type": "thread.started", "thread_id": "codex-thread"}) + "\n"
        await self._assert_cancel_returns_offset(
            tail_codex_output,
            line,
            "thread_id",
            "codex-thread",
        )

    async def test_cancelled_gemini_tail_returns_latest_offset(self):
        line = json.dumps({"type": "init", "session_id": "gemini-session"}) + "\n"
        await self._assert_cancel_returns_offset(
            tail_gemini_output,
            line,
            "session_id",
            "gemini-session",
        )

    async def test_cancelled_pi_tail_returns_latest_offset(self):
        line = json.dumps({"type": "session", "id": "pi-session"}) + "\n"
        await self._assert_cancel_returns_offset(
            tail_pi_output,
            line,
            "session_id",
            "pi-session",
        )


if __name__ == "__main__":
    unittest.main()
