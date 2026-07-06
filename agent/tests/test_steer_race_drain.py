"""Tests for the claude_code steer-race fix (plan-2662-steer-race.md, sub-task 1):
tail_ssh_output's _kill_tmux does a final synchronous drain of check_steer_fn
before tearing down the tmux session, so a steer message that the periodic
poll loop hasn't picked up yet still gets delivered instead of silently
racing a dead session.
"""

import json
import threading
import unittest
from unittest.mock import Mock

from agent.claude_code import tail_ssh_output


class _GatedLine:
    """A single-line channel whose line is withheld until `gate` is set.

    Used to guarantee the poll loop's first check_steer_fn() call (which
    happens immediately on thread start) completes before _read_lines
    observes the "result" line and tears the session down — otherwise the
    two threads race non-deterministically.
    """

    def __init__(self, line: str, gate: threading.Event):
        self._line = line
        self._gate = gate
        self._served = False
        self._closed = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        if not self._served:
            self._served = True
            self._gate.wait(2)
            return self._line
        while not self._closed:
            pass
        raise EOFError()

    def close(self):
        self._closed = True


class _StaggeredChecker:
    """Returns nothing on the poll loop's first call (opening the gate as it
    does), then the straggler steer message on the next call (the final
    drain inside _kill_tmux)."""

    def __init__(self, straggler, gate: threading.Event):
        self._straggler = straggler
        self._gate = gate
        self._calls = 0
        self.unclaim_calls = []

    def __call__(self):
        self._calls += 1
        if self._calls == 1:
            self._gate.set()
            return []
        if self._calls == 2:
            return [self._straggler]
        return []

    def unclaim(self, msg_id):
        self.unclaim_calls.append(msg_id)


def _make_client(gate: threading.Event, write_exit_code: int = 0):
    calls = []
    tail_stdout = _GatedLine(json.dumps({"type": "result", "session_id": "sess-1"}) + "\n", gate)

    def exec_command(cmd):
        calls.append(cmd)
        if cmd.startswith("tail -n"):
            return (Mock(), tail_stdout, Mock())
        if "printf" in cmd:
            write_stdout = Mock()
            write_stdout.channel.recv_exit_status.return_value = write_exit_code
            return (Mock(), write_stdout, Mock())
        generic_stdout = Mock()
        generic_stdout.channel.recv_exit_status.return_value = 0
        return (Mock(), generic_stdout, Mock())

    client = Mock()
    client.exec_command.side_effect = exec_command
    return client, calls


class SteerRaceDrainTest(unittest.IsolatedAsyncioTestCase):
    async def test_kill_tmux_drains_and_delivers_straggler_before_teardown(self):
        gate = threading.Event()
        client, calls = _make_client(gate)
        checker = _StaggeredChecker(("hello", "m-late", []), gate)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_steer_fn=checker,
        )

        self.assertEqual(result["consumed_steer_ids"], ["m-late"])
        self.assertEqual(checker.unclaim_calls, [])

        printf_index = next(i for i, c in enumerate(calls) if "printf" in c)
        kill_index = next(i for i, c in enumerate(calls) if "tmux kill-session" in c)
        self.assertLess(printf_index, kill_index)

    async def test_kill_tmux_unclaims_straggler_when_write_fails(self):
        gate = threading.Event()
        client, calls = _make_client(gate, write_exit_code=1)
        checker = _StaggeredChecker(("hello", "m-late", []), gate)

        result = await tail_ssh_output(
            chat_id="chat-1",
            vm_config=Mock(),
            offset=0,
            message_callback=lambda msg: None,
            ssh_client=client,
            check_steer_fn=checker,
        )

        self.assertEqual(result["consumed_steer_ids"], [])
        self.assertEqual(checker.unclaim_calls, ["m-late"])


if __name__ == "__main__":
    unittest.main()
