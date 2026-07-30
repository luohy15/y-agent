"""Affirmative detection of a refused resume handle (todo 2930 follow-up).

The worker clears `chat.external_id` only when Claude Code itself named the
handle as the cause, so this probe is the single source of that decision. What
matters here is that it reports True *only* on the CLI's own refusal message and
fails safe (False) in every other situation, including when it cannot run.
"""

import json
import unittest
from unittest.mock import Mock

from agent.claude_code import RESUME_REFUSED_MARKER, tail_ssh_output


class EmptyChannel:
    """A tail channel that yields no lines and closes immediately: the process
    is already gone and never wrote a result event."""

    def __init__(self):
        self.channel = self

    def __iter__(self):
        return iter([])

    def close(self):
        pass


class OneLineThenClose:
    def __init__(self, line: str):
        self._line = line
        self._served = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        if self._served:
            raise StopIteration
        self._served = True
        return self._line

    def close(self):
        pass


def _ssh_ok(text: str = "") -> tuple:
    stdout = Mock()
    stdout.channel.recv_exit_status.return_value = 0
    stdout.read.return_value = text.encode()
    stderr = Mock()
    stderr.read.return_value = b""
    return (Mock(), stdout, stderr)


def _ssh_fail(err: str = "boom") -> tuple:
    stdout = Mock()
    stdout.channel.recv_exit_status.return_value = 1
    stdout.read.return_value = b""
    stderr = Mock()
    stderr.read.return_value = err.encode()
    return (Mock(), stdout, stderr)


def _make_client(tail_channel, *, stderr_text: str = "", exit_code: str = "1",
                 stderr_readable: bool = True):
    """Mock SSH client for the no-result branch: routes the sentinel check, the
    tmux liveness check, the stderr probe and the exit-code read by substring."""
    calls = []

    def exec_command(cmd, *args, **kwargs):
        calls.append(cmd)
        if "wait $TAIL_PID" in cmd:
            return (Mock(), tail_channel, Mock())
        if "killed" in cmd:
            return _ssh_ok("")
        if "has-session" in cmd:
            return _ssh_ok("dead\n")
        if ".stderr" in cmd:
            return _ssh_ok(stderr_text) if stderr_readable else _ssh_fail()
        if cmd.strip().startswith("cat "):
            return _ssh_ok(exit_code)
        return _ssh_ok("")

    client = Mock()
    client.exec_command.side_effect = exec_command
    return client, calls


async def _tail(client):
    return await tail_ssh_output(
        chat_id="chat-1",
        vm_config=Mock(),
        offset=0,
        message_callback=lambda msg: None,
        ssh_client=client,
    )


class ResumeRefusedProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_stderr_refusal_sets_the_flag_and_names_the_cause(self):
        client, calls = _make_client(
            EmptyChannel(),
            stderr_text=f"{RESUME_REFUSED_MARKER}: 0b3c4d5e-1111-2222-3333-444455556666\n",
        )
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["resume_refused"])
        self.assertIn("refused the recorded session id", result["result_data"]["result"])
        self.assertTrue(any(".stderr" in c for c in calls))

    async def test_unrelated_startup_stderr_does_not_set_the_flag(self):
        """A missing/broken binary, bad credentials or a bad --model all land in
        the same no-result branch. None of them says anything about the handle."""
        client, _ = _make_client(
            EmptyChannel(),
            stderr_text="node: bad option: --effort\n",
            exit_code="127",
        )
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["resume_refused"])
        self.assertIn("process exited with code 127", result["result_data"]["result"])

    async def test_empty_stderr_does_not_set_the_flag(self):
        client, _ = _make_client(EmptyChannel(), stderr_text="")
        result = await _tail(client)
        self.assertFalse(result["resume_refused"])

    async def test_unreadable_stderr_fails_safe(self):
        """If the probe cannot run, report no refusal: a missed refusal costs one
        wedged turn, a false one costs a live session."""
        client, _ = _make_client(EmptyChannel(), stderr_readable=False)
        result = await _tail(client)
        self.assertFalse(result["resume_refused"])

    async def test_launcher_work_dir_failure_never_probes_stderr(self):
        """`work_dir not found` is a synthetic result event written to stdout by
        the launcher before tmux starts, so it never enters the no-result branch
        and can never be mistaken for a refusal."""
        line = json.dumps({
            "type": "result", "is_error": True, "result": "work_dir not found: /repo",
        }) + "\n"
        client, calls = _make_client(OneLineThenClose(line))
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["resume_refused"])
        self.assertFalse(any(".stderr" in c for c in calls))


if __name__ == "__main__":
    unittest.main()
