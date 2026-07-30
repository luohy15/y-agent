"""Unit tests for agent.claude_usage.parse_usage_pane (sub-task 1, re-verified
against the live overlay in sub-task 2b).

`/usage` is a pure client-side TUI overlay; the only data source is the captured
pane. These tests pin the label -> next-3-lines scan against two verbatim pane
blocks: the original spike recording (CC v2.1.177) and a live re-capture (CC
v2.1.220, todo 2872 sub-task 2b) that confirmed the third window's label is not
stable text -- it read "Current week (Sonnet only)" on 2.1.177 and
"Current week (Fable)" on 2.1.220 for the same account, because Anthropic
renames it per active model/promo (see the "Fable 5" promo banner). The parser
now matches that window generically (`week_extra`, carrying the observed
`label`) instead of pinning "Sonnet". Also assert the garbled-fixture fallback
(`parse_ok=False`, `raw` populated).
"""

import unittest

from agent.claude_usage import parse_usage_pane


# Verbatim /usage overlay block recorded on the EC2 box (spike 2026-06-15, CC v2.1.177).
_FIXTURE_2_1_177 = """\
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

# Verbatim /usage overlay block recorded on the EC2 box (todo 2872 sub-task 2b
# live re-capture, 2026-07-30, CC v2.1.220). Note the added "Session" stats
# block above the windows, the "+50% weekly limits promo" line sharing the
# week_all window, and "Current week (Fable)" replacing "(Sonnet only)".
_FIXTURE_2_1_220 = """\
  Settings  Status   Config   Usage   Stats

  Session

  Total cost:            $0.0000
  Total duration (API):  0s
  Total duration (wall): 7s
  Total code changes:    0 lines added, 0 lines removed
  Usage:                 0 input, 0 output, 0 cache read, 0 cache write

  Current session
  ██████████                                         20% used
  Resets 4:30pm (UTC)

  Current week (all models)
  ███████████▌                                       23% used
  Resets Aug 5, 9am (UTC)
  +50% weekly limits promo through Aug 19 · clau.de/cc-50-promo

  Current week (Fable)
  ████                                               8% used
  Resets Aug 5, 9am (UTC)
"""


class TestParseUsagePane(unittest.TestCase):
    def test_parses_all_three_windows_2_1_177(self):
        result = parse_usage_pane(_FIXTURE_2_1_177)

        self.assertTrue(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 15, "reset": "4:59am (UTC)"})
        self.assertEqual(result["week_all"], {"percent": 4, "reset": "Jun 17, 8:59am (UTC)"})
        self.assertEqual(
            result["week_extra"],
            {"label": "Sonnet only", "percent": 0, "reset": "Jun 17, 9am (UTC)"},
        )
        self.assertEqual(result["raw"], _FIXTURE_2_1_177)

    def test_parses_all_three_windows_2_1_220_live(self):
        result = parse_usage_pane(_FIXTURE_2_1_220)

        self.assertTrue(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 20, "reset": "4:30pm (UTC)"})
        self.assertEqual(result["week_all"], {"percent": 23, "reset": "Aug 5, 9am (UTC)"})
        self.assertEqual(
            result["week_extra"],
            {"label": "Fable", "percent": 8, "reset": "Aug 5, 9am (UTC)"},
        )
        self.assertEqual(result["raw"], _FIXTURE_2_1_220)

    def test_garbled_pane_marks_parse_not_ok_but_keeps_raw(self):
        garbled = "some unrelated TUI output\nnothing useful here\n"
        result = parse_usage_pane(garbled)

        self.assertFalse(result["parse_ok"])
        self.assertIsNone(result["session"])
        self.assertIsNone(result["week_all"])
        self.assertIsNone(result["week_extra"])
        self.assertEqual(result["raw"], garbled)

    def test_partial_pane_is_not_ok(self):
        # Only the session window rendered (e.g. capture mid-render).
        partial = "  Current session\n  ████  15% used\n  Resets 4:59am (UTC)\n"
        result = parse_usage_pane(partial)

        self.assertFalse(result["parse_ok"])
        self.assertEqual(result["session"], {"percent": 15, "reset": "4:59am (UTC)"})
        self.assertIsNone(result["week_all"])

    def test_two_window_overlay_is_ok_without_extra(self):
        # Live overlay (CC 2.1.x) renders only session + week_all, followed by a
        # "What's contributing" section and no third weekly window.
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
        self.assertIsNone(result["week_extra"])


if __name__ == "__main__":
    unittest.main()
