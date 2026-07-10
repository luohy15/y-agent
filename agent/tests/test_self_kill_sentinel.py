"""Tests for the self-kill sentinel fix (plan-2751, Fix A):

When we tear down a detached session ourselves (steer or interrupt kill), we
drop a sentinel file (`/tmp/cc-<chat_id>.killed`) so a subsequent no-result
check — even a fresh `tail_codex_output`/`tail_ssh_output` call after a
Lambda handoff, which has no memory of this call's local
`steer_requested`/interrupted state — can tell our own teardown apart from a
genuine external crash and skip the "exited before producing output" death
report.
"""

import json
import unittest
from unittest.mock import Mock

from agent.claude_code import _kill_session_marking_self_killed, tail_ssh_output
from agent.codex import tail_codex_output


class EmptyChannel:
    """A channel that yields no lines and closes immediately, simulating a
    tail command that ends without observing any output (e.g. the remote
    session was already torn down before this tail call started)."""

    def __init__(self):
        self.channel = self

    def __iter__(self):
        return iter([])

    def close(self):
        pass


class BlockingChannel:
    """A channel that yields no lines and blocks until closed, simulating a
    live `tail -f` against a session that is still running."""

    def __init__(self):
        self._closed = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        while not self._closed:
            pass
        raise EOFError()

    def close(self):
        self._closed = True


class OneLineThenBlock:
    """A channel that yields a single line, then blocks until closed."""

    def __init__(self, first_line: str):
        self._first = first_line
        self._served = False
        self._closed = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        if not self._served:
            self._served = True
            return self._first
        while not self._closed:
            pass
        raise EOFError()

    def close(self):
        self._closed = True


def _ssh_ok(text: str = "") -> tuple:
    stdout = Mock()
    stdout.channel.recv_exit_status.return_value = 0
    stdout.read.return_value = text.encode()
    stderr = Mock()
    stderr.read.return_value = b""
    return (Mock(), stdout, stderr)


def _make_client(tail_channel, *, sentinel_present: bool, tmux_alive: bool = False, exit_code: str = ""):
    """Build a mock SSH client for the no-result branch scenarios.

    Routes `client.exec_command(cmd)` calls by substring so the sentinel
    check/consume, tmux liveness check, and exit-code read used by the
    no-result branch each get a distinct, deterministic reply.
    """
    calls = []

    def exec_command(cmd, *args, **kwargs):
        calls.append(cmd)
        if "wait $TAIL_PID" in cmd:
            return (Mock(), tail_channel, Mock())
        if "killed" in cmd:
            return _ssh_ok("yes\n" if sentinel_present else "")
        if "has-session" in cmd:
            return _ssh_ok("alive\n" if tmux_alive else "dead\n")
        if cmd.strip().startswith("cat "):
            return _ssh_ok(exit_code)
        return _ssh_ok("")

    client = Mock()
    client.exec_command.side_effect = exec_command
    return client, calls


class CodexSelfKillSentinelTest(unittest.IsolatedAsyncioTestCase):
    async def test_steer_kill_writes_self_kill_sentinel(self):
        """_on_steer_detached must drop the sentinel as part of its teardown."""
        channel = BlockingChannel()
        client, calls = _make_client(channel, sentinel_present=False)

        result = await tail_codex_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_steer_fn=Mock(side_effect=[[("steer text", "m1", [])]] + [[]] * 20),
        )

        self.assertEqual(result["status"], "steer")
        self.assertTrue(any("touch" in c and "killed" in c for c in calls))

    async def test_steer_kill_marks_before_killing_tmux_in_same_command(self):
        """The marker write must precede the destructive kill, and both must
        be in the same remote command, so a channel/process death between
        the two can never happen (request-changes finding 1)."""
        channel = BlockingChannel()
        client, calls = _make_client(channel, sentinel_present=False)

        await tail_codex_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_steer_fn=Mock(side_effect=[[("steer text", "m1", [])]] + [[]] * 20),
        )

        kill_cmds = [c for c in calls if "tmux kill-session" in c]
        self.assertEqual(len(kill_cmds), 1)
        cmd = kill_cmds[0]
        self.assertIn("touch", cmd)
        self.assertLess(cmd.index("touch"), cmd.index("tmux kill-session"))

    async def test_reader_thread_interrupt_teardown_also_writes_sentinel(self):
        """The second, reader-thread interrupt teardown inside _read_lines
        (racing the watchdog) must go through the same marker-first helper
        (request-changes finding 2)."""
        line = json.dumps({"type": "thread.started", "thread_id": "codex-thread"}) + "\n"
        channel = OneLineThenBlock(line)
        client, calls = _make_client(channel, sentinel_present=False)

        result = await tail_codex_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_interrupted_fn=Mock(return_value=True),
        )

        self.assertEqual(result["status"], "interrupted")
        kill_cmds = [c for c in calls if "tmux kill-session" in c]
        self.assertTrue(kill_cmds)
        for cmd in kill_cmds:
            self.assertIn("killed", cmd)
            self.assertLess(cmd.index("touch"), cmd.index("tmux kill-session"))

    async def test_no_result_branch_suppresses_death_when_self_killed(self):
        """A fresh call (no local steer/interrupt state this pass) that finds
        the sentinel on disk must resume monitoring, not report a death."""
        channel = EmptyChannel()
        client, calls = _make_client(channel, sentinel_present=True)

        result = await tail_codex_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
        )

        self.assertEqual(result["status"], "monitoring")
        self.assertFalse(result["is_done"])
        self.assertNotIn("exited before producing output", json.dumps(result))
        # the sentinel must be consumed (checked + removed) via one command
        self.assertTrue(any("killed" in c for c in calls))
        # since self_killed short-circuits, the tmux liveness check is skipped
        self.assertFalse(any("has-session" in c for c in calls))

    async def test_no_result_branch_still_reports_death_without_sentinel(self):
        """Regression guard: an external death with no sentinel must still be
        reported (the sentinel check must not swallow real crashes)."""
        channel = EmptyChannel()
        client, calls = _make_client(channel, sentinel_present=False, tmux_alive=False, exit_code="")

        result = await tail_codex_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("exited before producing output", result["result_data"]["result"])


class ClaudeCodeSelfKillSentinelTest(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_kill_writes_self_kill_sentinel(self):
        """_kill_detached must drop the sentinel as part of its teardown."""
        channel = BlockingChannel()
        client, calls = _make_client(channel, sentinel_present=False)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_interrupted_fn=Mock(side_effect=[True] + [True] * 20),
        )

        self.assertEqual(result["status"], "interrupted")
        self.assertTrue(any("touch" in c and "killed" in c for c in calls))

    async def test_kill_detached_marks_before_killing_tmux_in_same_command(self):
        """Command-shape regression: marker creation gates the kill (`&&`),
        not just precedes it in text order (re-review finding 2)."""
        channel = BlockingChannel()
        client, calls = _make_client(channel, sentinel_present=False)

        await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_interrupted_fn=Mock(side_effect=[True] + [True] * 20),
        )

        kill_cmds = [c for c in calls if "tmux kill-session" in c]
        self.assertEqual(len(kill_cmds), 1)
        cmd = kill_cmds[0]
        self.assertIn("touch /tmp/cc-chat-1.killed && tmux kill-session", cmd)

    async def test_reader_thread_interrupt_teardown_also_writes_sentinel(self):
        """Claude Code's reader-thread interrupt path (_read_lines calling
        _kill_tmux(self_killed=True)), which races the watchdog's
        _kill_detached, must also route through the marker-first helper
        (re-review finding 1)."""
        line = json.dumps({"type": "system", "session_id": "sess-1"}) + "\n"
        channel = OneLineThenBlock(line)
        client, calls = _make_client(channel, sentinel_present=False)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_interrupted_fn=Mock(return_value=True),
        )

        self.assertEqual(result["status"], "interrupted")
        kill_cmds = [c for c in calls if "tmux kill-session" in c]
        self.assertTrue(kill_cmds)
        for cmd in kill_cmds:
            self.assertIn("touch /tmp/cc-chat-1.killed && tmux kill-session", cmd)

    async def test_result_completion_teardown_does_not_write_sentinel(self):
        """The normal result-completion path (_kill_tmux with the default
        self_killed=False) must NOT mark the session as self-killed — it
        already has result_data, so no no-result branch could misfire, and
        marking it would be semantically wrong (not a self-kill for the
        false-death race)."""
        line = json.dumps({"type": "result", "session_id": "sess-1"}) + "\n"
        channel = OneLineThenBlock(line)
        client, calls = _make_client(channel, sentinel_present=False)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
        )

        self.assertEqual(result["status"], "completed")
        kill_cmds = [c for c in calls if "tmux kill-session" in c]
        self.assertEqual(len(kill_cmds), 1)
        self.assertNotIn("killed", kill_cmds[0])

    async def test_no_result_branch_suppresses_death_when_self_killed(self):
        channel = EmptyChannel()
        client, calls = _make_client(channel, sentinel_present=True)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
        )

        self.assertEqual(result["status"], "monitoring")
        self.assertFalse(result["is_done"])
        self.assertNotIn("exited before producing output", json.dumps(result))
        self.assertTrue(any("killed" in c for c in calls))
        self.assertFalse(any("has-session" in c for c in calls))

    async def test_no_result_branch_still_reports_death_without_sentinel(self):
        channel = EmptyChannel()
        client, calls = _make_client(channel, sentinel_present=False, tmux_alive=False, exit_code="")

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("exited before producing output", result["result_data"]["result"])


class KillSessionMarkingSelfKilledTest(unittest.TestCase):
    """Direct tests of the shared helper's command shape and failure
    handling (re-review finding 2): the kill must be conditional on marker
    creation (`&&`, not `;`), and a failed remote command must not raise."""

    def test_command_shape_gates_kill_on_marker_creation(self):
        client, calls = _make_client(EmptyChannel(), sentinel_present=False)

        _kill_session_marking_self_killed(client, "chat-1")

        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertIn("touch /tmp/cc-chat-1.killed && tmux kill-session", cmd)
        self.assertNotIn("touch /tmp/cc-chat-1.killed; tmux kill-session", cmd)
        # cleanup always runs, independent of the marker+kill chain
        self.assertIn("rm -f /tmp/cc-chat-1.stdin /tmp/cc-chat-1.exit", cmd)

    def test_failed_remote_command_does_not_raise(self):
        calls = []

        def exec_command(cmd, *args, **kwargs):
            calls.append(cmd)
            stdout = Mock()
            stdout.channel.recv_exit_status.return_value = 1
            stdout.read.return_value = b""
            stderr = Mock()
            stderr.read.return_value = b"touch: permission denied"
            return (Mock(), stdout, stderr)

        client = Mock()
        client.exec_command.side_effect = exec_command

        # must not raise even though the remote command reports failure
        _kill_session_marking_self_killed(client, "chat-1")

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
