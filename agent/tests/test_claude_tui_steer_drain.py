"""Tests for the claude_tui steer-race fixes (plan-2704-steer-prd-gap.md,
sub-tasks 1-2):

- sub-task 1: `_on_steer` returns True on a confirmed paste and False on a
  paste exception, so the poll loop unclaims a failed delivery instead of
  silently dropping it (mirrors agent/tests/test_poll_loop_unclaim.py).
- sub-task 2: the done-branch teardown does a final synchronous drain of
  check_steer_fn before killing the tmux session, delivering (or unclaiming)
  any straggler that the periodic poll hasn't picked up yet (mirrors
  agent/tests/test_steer_race_drain.py for claude_code).
"""

import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

import agent.claude_tui as claude_tui
from agent.claude_tui import tail_claude_tui_output


class FakeTuiClient:
    """Minimal SSH client stand-in; `_ssh_exec` is patched to call `ssh_exec`
    below, tmux/session commands go through `exec_command` and are recorded
    for ordering assertions."""

    def __init__(self, lines=None, tail_gate: threading.Event = None):
        self.lines = list(lines or [])
        self.commands = []
        self._tail_gate = tail_gate

    def exec_command(self, cmd):
        self.commands.append(cmd)
        stdout = Mock()
        stdout.channel.recv_exit_status.return_value = 0
        return (Mock(), stdout, Mock())

    def ssh_exec(self, _client, cmd):
        if cmd == "echo $HOME":
            return "/home/test\n"
        if cmd.startswith("tail -n +"):
            if self._tail_gate is not None:
                self._tail_gate.wait(2)
            start = int(cmd.split("tail -n +", 1)[1].split(" ", 1)[0]) - 1
            selected = self.lines[start:]
            return ("\n".join(selected) + "\n") if selected else ""
        if cmd.startswith("tmux capture-pane"):
            return ""
        return ""


def _turn_duration_line():
    return json.dumps({"type": "system", "subtype": "turn_duration"})


class ClaudeTuiOnSteerReturnValueTest(unittest.IsolatedAsyncioTestCase):
    """Sub-task 1: the live mid-turn paste path returns True/False."""

    async def _tail(self, checker, paste_side_effect):
        fake = FakeTuiClient(lines=[])
        started = time.monotonic()
        with (
            patch.object(claude_tui, "_ssh_exec", side_effect=fake.ssh_exec),
            patch.object(claude_tui, "_paste_prompt", side_effect=paste_side_effect),
            patch.object(claude_tui, "_tmux_session_alive", return_value=True),
            patch.object(claude_tui, "POLL_INTERVAL_SECONDS", 0.01),
        ):
            return await tail_claude_tui_output(
                chat_id="chat-1",
                vm_config=Mock(work_dir="/work"),
                work_dir="/work",
                session_id="session-1",
                ssh_client=fake,
                check_steer_fn=checker,
                check_deadline_fn=lambda: time.monotonic() - started > 0.1,
            )

    async def test_on_steer_returns_true_and_is_not_unclaimed_on_success(self):
        checker = Mock(side_effect=[[("hello", "m1", [])]] + [[]] * 50)
        checker.unclaim = Mock()

        result = await self._tail(checker, paste_side_effect=lambda *a: None)

        self.assertEqual(result["consumed_steer_ids"], ["m1"])
        checker.unclaim.assert_not_called()

    async def test_on_steer_returns_false_and_is_unclaimed_on_paste_failure(self):
        checker = Mock(side_effect=[[("hello", "m1", [])]] + [[]] * 50)
        checker.unclaim = Mock()

        def _fail(*_a):
            raise RuntimeError("paste failed")

        result = await self._tail(checker, paste_side_effect=_fail)

        self.assertEqual(result["consumed_steer_ids"], [])
        checker.unclaim.assert_called_once_with("m1")


class _StaggeredChecker:
    """Returns nothing on the poll loop's first call (opening the tail gate
    as it does), then the straggler steer message on the next call (the
    final drain inside the done-branch teardown)."""

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


class ClaudeTuiSteerDrainTest(unittest.IsolatedAsyncioTestCase):
    """Sub-task 2: final drain before the done-branch tmux kill."""

    async def _tail(self, checker, gate, paste_side_effect):
        fake = FakeTuiClient(lines=[_turn_duration_line()], tail_gate=gate)
        with (
            patch.object(claude_tui, "_ssh_exec", side_effect=fake.ssh_exec),
            patch.object(claude_tui, "_paste_prompt", side_effect=paste_side_effect),
            patch.object(claude_tui, "_tmux_session_alive", return_value=True),
            patch.object(claude_tui, "POLL_INTERVAL_SECONDS", 0.001),
        ):
            result = await tail_claude_tui_output(
                chat_id="chat-1",
                vm_config=Mock(work_dir="/work"),
                work_dir="/work",
                session_id="session-1",
                ssh_client=fake,
                check_steer_fn=checker,
            )
        return result, fake

    async def test_done_branch_drains_and_delivers_straggler_before_kill(self):
        gate = threading.Event()
        checker = _StaggeredChecker(("hello", "m-late", []), gate)

        calls_order = []

        def _paste_recording(_client, _chat_id, _text):
            calls_order.append("paste")

        result, fake = await self._tail(checker, gate, paste_side_effect=_paste_recording)

        self.assertEqual(result["consumed_steer_ids"], ["m-late"])
        self.assertEqual(checker.unclaim_calls, [])
        # The straggler paste happened (recorded) before the drain proceeds
        # to issue the teardown's kill-session command.
        self.assertEqual(calls_order, ["paste"])
        self.assertTrue(any("tmux kill-session" in c for c in fake.commands))

    async def test_done_branch_unclaims_straggler_when_paste_fails(self):
        gate = threading.Event()
        checker = _StaggeredChecker(("hello", "m-late", []), gate)

        def _fail(*_a):
            raise RuntimeError("paste failed")

        result, fake = await self._tail(checker, gate, paste_side_effect=_fail)

        self.assertEqual(result["consumed_steer_ids"], [])
        self.assertEqual(checker.unclaim_calls, ["m-late"])
        self.assertTrue(any("tmux kill-session" in c for c in fake.commands))


if __name__ == "__main__":
    unittest.main()
