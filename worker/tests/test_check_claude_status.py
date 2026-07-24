import unittest

from worker.steps.check_claude_status import ALL_CLAUDE_BOTS, MODEL_BOT_MAP, _affected_bots


class AffectedBotsTest(unittest.TestCase):
    def test_opus_incident_maps_to_claude_code_only(self):
        # claude_tui is removed; opus incidents must no longer surface it.
        self.assertEqual(_affected_bots("Elevated errors for Claude Opus 4.6"), ["claude_code"])

    def test_across_models_incident_uses_all_claude_bots_without_claude_tui(self):
        self.assertEqual(_affected_bots("Degraded performance across all models"), ALL_CLAUDE_BOTS)
        self.assertNotIn("claude_tui", ALL_CLAUDE_BOTS)

    def test_model_bot_map_has_no_claude_tui_entries(self):
        for bots in MODEL_BOT_MAP.values():
            self.assertNotIn("claude_tui", bots)

    def test_unrecognized_model_returns_empty(self):
        self.assertEqual(_affected_bots("Some unrelated incident"), [])


if __name__ == "__main__":
    unittest.main()
