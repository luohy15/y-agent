"""Unit tests for the sub-task 3 additions to `agent.claude_usage`:
`reset_at_iso` (localized reset text -> absolute UTC timestamp) and
`extra_window_key` (dynamic label -> extra_windows key)."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from agent.claude_usage import _run_local, extra_window_key, reset_at_iso


class RunLocalTest(unittest.TestCase):
    def test_zero_exit_returns_stdout(self):
        completed = MagicMock(returncode=0, stdout="hello\n", stderr="")
        with patch("agent.claude_usage.subprocess.run", return_value=completed) as run:
            out = _run_local("echo hello")

        run.assert_called_once_with(["bash", "-lc", "echo hello"], capture_output=True, text=True)
        self.assertEqual(out, "hello\n")

    def test_nonzero_exit_raises(self):
        completed = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch("agent.claude_usage.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError):
                _run_local("false")

    def test_no_server_running_is_tolerated(self):
        completed = MagicMock(returncode=1, stdout="", stderr="no server running on ...")
        with patch("agent.claude_usage.subprocess.run", return_value=completed):
            out = _run_local("tmux kill-session -t x")
        self.assertEqual(out, "")

    def test_session_not_found_is_tolerated(self):
        completed = MagicMock(returncode=1, stdout="", stderr="session not found: x")
        with patch("agent.claude_usage.subprocess.run", return_value=completed):
            out = _run_local("tmux kill-session -t x")
        self.assertEqual(out, "")


class ResetAtIsoTest(unittest.TestCase):
    def test_bare_time_before_now_rolls_to_tomorrow(self):
        now = datetime(2026, 7, 30, 10, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("4:59am (UTC)", now=now)
        self.assertEqual(result, "2026-07-31T04:59:00Z")

    def test_bare_time_after_now_stays_today(self):
        now = datetime(2026, 7, 30, 2, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("4:59am (UTC)", now=now)
        self.assertEqual(result, "2026-07-30T04:59:00Z")

    def test_bare_time_without_minutes(self):
        now = datetime(2026, 7, 30, 2, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("5am (UTC)", now=now)
        self.assertEqual(result, "2026-07-30T05:00:00Z")

    def test_date_and_time_this_year(self):
        now = datetime(2026, 7, 30, 0, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("Aug 5, 9am (UTC)", now=now)
        self.assertEqual(result, "2026-08-05T09:00:00Z")

    def test_date_with_minutes(self):
        now = datetime(2026, 7, 30, 0, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("Jun 17, 8:59am (UTC)", now=now)
        # More than a day in the past relative to "now" -> next year's occurrence.
        self.assertEqual(result, "2027-06-17T08:59:00Z")

    def test_pm_hour_conversion(self):
        now = datetime(2026, 7, 30, 0, 0, 0, tzinfo=timezone.utc)
        result = reset_at_iso("4:30pm (UTC)", now=now)
        self.assertEqual(result, "2026-07-30T16:30:00Z")

    def test_none_input_returns_none(self):
        self.assertIsNone(reset_at_iso(None))

    def test_unrecognized_text_returns_none_not_a_guess(self):
        self.assertIsNone(reset_at_iso("sometime soon"))


class ExtraWindowKeyTest(unittest.TestCase):
    def test_simple_label(self):
        self.assertEqual(extra_window_key("Fable"), "one_week_fable")

    def test_multi_word_label_is_slugified(self):
        self.assertEqual(extra_window_key("Sonnet only"), "one_week_sonnet_only")

    def test_empty_label_has_a_fallback(self):
        self.assertEqual(extra_window_key(""), "one_week_extra")


if __name__ == "__main__":
    unittest.main()
