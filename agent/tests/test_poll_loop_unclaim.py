import time
import unittest
from unittest.mock import Mock

from agent.poll_loop import PollLoop


class PollLoopUnclaimTest(unittest.TestCase):
    """PollLoop must release a checker's claim on a message when on_steer
    reports the delivery failed (returns False), so the message stays
    available for the next mechanism to pick up (plan-2662-steer-race.md)."""

    def _run_loop(self, on_steer_result):
        check_steer_fn = Mock(side_effect=[[("text", "m1", [])]] + [[]] * 20)
        check_steer_fn.unclaim = Mock()
        on_steer = Mock(return_value=on_steer_result)

        loop = PollLoop(check_steer_fn=check_steer_fn, on_steer=on_steer)
        loop.start()
        time.sleep(0.05)
        loop.stop()

        on_steer.assert_called_once_with("text", "m1", [])
        return check_steer_fn

    def test_unclaim_called_when_delivery_fails(self):
        check_steer_fn = self._run_loop(on_steer_result=False)
        check_steer_fn.unclaim.assert_called_once_with("m1")

    def test_unclaim_not_called_when_delivery_succeeds(self):
        check_steer_fn = self._run_loop(on_steer_result=True)
        check_steer_fn.unclaim.assert_not_called()

    def test_unclaim_not_called_when_on_steer_returns_none(self):
        # Backends (codex/gemini/pi/claude_tui) that can't confirm delivery
        # return None from on_steer — must be treated as success, not failure.
        check_steer_fn = self._run_loop(on_steer_result=None)
        check_steer_fn.unclaim.assert_not_called()

    def test_missing_unclaim_hook_does_not_raise(self):
        # A plain function has no `.unclaim` attribute (unlike a Mock, which
        # would auto-vivify one on access) — exercises the getattr(..., None)
        # fallback in PollLoop._loop.
        calls = []

        def check_steer_fn():
            calls.append(1)
            return [("text", "m1", [])] if len(calls) == 1 else []

        on_steer = Mock(return_value=False)

        loop = PollLoop(check_steer_fn=check_steer_fn, on_steer=on_steer)
        loop.start()
        time.sleep(0.05)
        loop.stop()

        on_steer.assert_called_once_with("text", "m1", [])


if __name__ == "__main__":
    unittest.main()
