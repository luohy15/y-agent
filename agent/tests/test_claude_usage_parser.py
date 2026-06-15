"""Unit tests for agent.claude_usage.parse_usage_pane (sub-task 1).

`/usage` is a pure client-side TUI overlay; the only data source is the captured
pane. These tests pin the label -> next-3-lines scan against the verbatim pane
block recorded during the spike (CC v2.1.177), and assert the garbled-fixture
fallback (`parse_ok=False`, `raw` populated).
"""

import unittest

from agent.claude_usage import parse_usage_pane


# Verbatim /usage overlay block recorded on the EC2 box (spike 2026-06-15).
_FIXTURE = """\
  Settings  Status  Config  Usage  Stats

  Current session
  ███████▌                                           15% used
  Resets 4:59am (UTC)

  Current week (all models)
  ██                                                 4% used
  Resets Jun 17, 8:59am (UTC)

  Current week (Sonnet only)
                                                     0% used
  Resets Jun 17, 9am (UTC)
"""


class TestParseUsagePane(unittest.TestCase):
    def test_parses_all_three_windows(self):
        result = parse_usage_pane(_FIXTURE)

        self.assertTrue(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 15, "reset": "4:59am (UTC)"})
        self.assertEqual(result["week_all"], {"percent": 4, "reset": "Jun 17, 8:59am (UTC)"})
        self.assertEqual(result["week_sonnet"], {"percent": 0, "reset": "Jun 17, 9am (UTC)"})
        self.assertEqual(result["raw"], _FIXTURE)

    def test_garbled_pane_marks_parse_not_ok_but_keeps_raw(self):
        garbled = "some unrelated TUI output\nnothing useful here\n"
        result = parse_usage_pane(garbled)

        self.assertFalse(result["parse_ok"])
        self.assertIsNone(result["session"])
        self.assertIsNone(result["week_all"])
        self.assertIsNone(result["week_sonnet"])
        self.assertEqual(result["raw"], garbled)

    def test_partial_pane_is_not_ok(self):
        # Only the session window rendered (e.g. capture mid-render).
        partial = "  Current session\n  ████  15% used\n  Resets 4:59am (UTC)\n"
        result = parse_usage_pane(partial)

        self.assertFalse(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 15, "reset": "4:59am (UTC)"})
        self.assertIsNone(result["week_all"])

    def test_two_window_overlay_is_ok_without_sonnet(self):
        # Live overlay (CC 2.1.x) renders only session + week_all, followed by a
        # "What's contributing" section and no "Current week (Sonnet only)".
        two_window = """\
  Current session
  ███████▌                                           15% used
  Resets 5am (UTC)

  Current week (all models)
  █▌                                                 3% used
  Resets Jun 17, 9am (UTC)

  What's contributing to your limits usage?
"""
        result = parse_usage_pane(two_window)

        self.assertTrue(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 15, "reset": "5am (UTC)"})
        self.assertEqual(result["week_all"], {"percent": 3, "reset": "Jun 17, 9am (UTC)"})
        self.assertIsNone(result["week_sonnet"])


if __name__ == "__main__":
    unittest.main()
