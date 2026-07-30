"""`y usage limits [--json] [--refresh]` (todo 2872 sub-task 3): pins the
exact envelope shape and argv the backend's SSH wrapper is built against,
`--refresh` threading to the claude_tui_usage reader only (the two HTTP
readers always run fresh), and that one reader raising doesn't take the
others down with it.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from yagent.command_option import cli


def _claude_row(**overrides):
    row = {
        "backend": "claude_code", "provider": "anthropic", "account_id": None,
        "account_name": None, "observed_at": "2026-07-30T00:00:00Z",
        "source": "claude_tui_usage", "availability": "available", "error": None,
        "windows": {
            "five_hour": {"used_percent": 15.0, "reset_at": "2026-07-30T04:59:00Z"},
            "one_week": {"used_percent": 4.0, "reset_at": "2026-08-05T08:59:00Z"},
        },
        "extra_windows": {},
    }
    row.update(overrides)
    return row


def _codex_row(**overrides):
    row = {
        "backend": "codex", "provider": "openai", "account_id": None,
        "account_name": None, "observed_at": "2026-07-30T00:00:00Z",
        "source": "codex_usage_api", "availability": "available", "error": None,
        "windows": {
            "five_hour": {"used_percent": 12.0, "reset_at": None},
            "one_week": {"used_percent": 1.0, "reset_at": None},
        },
        "extra_windows": {},
    }
    row.update(overrides)
    return row


def _xai_row(**overrides):
    row = {
        "backend": "grok", "provider": "xai", "account_id": None,
        "account_name": None, "observed_at": "2026-07-30T00:00:00Z",
        "source": "xai_billing_credits", "availability": "available", "error": None,
        "windows": {"billing_period": {"used_percent": 42.0, "reset_at": None}},
        "extra_windows": {},
    }
    row.update(overrides)
    return row


class UsageLimitsCommandTest(unittest.TestCase):
    def _invoke(self, argv):
        runner = CliRunner()
        with patch(
            "yagent.commands.usage._claude_reader.read_claude_provider",
            new=AsyncMock(return_value=_claude_row()),
        ) as claude_mock, \
             patch(
                 "yagent.commands.usage._http_readers.read_codex_provider",
                 return_value=_codex_row(),
             ), \
             patch(
                 "yagent.commands.usage._http_readers.read_xai_provider",
                 return_value=_xai_row(),
             ):
            result = runner.invoke(cli, argv)
        return result, claude_mock

    def test_json_envelope_shape_and_backend_values(self):
        result, _ = self._invoke(["usage", "limits", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(set(envelope.keys()), {"providers", "errors"})
        backends = sorted(p["backend"] for p in envelope["providers"])
        self.assertEqual(backends, ["claude_code", "codex", "grok"])
        providers = {p["backend"]: p for p in envelope["providers"]}
        self.assertEqual(providers["claude_code"]["provider"], "anthropic")
        self.assertEqual(providers["codex"]["provider"], "openai")
        self.assertEqual(providers["grok"]["provider"], "xai")
        self.assertEqual(envelope["errors"], [])

    def test_refresh_flag_threads_to_claude_reader_only(self):
        result, claude_mock = self._invoke(["usage", "limits", "--json", "--refresh"])

        self.assertEqual(result.exit_code, 0, result.output)
        claude_mock.assert_awaited_once_with(refresh=True)

    def test_no_refresh_flag_passes_refresh_false(self):
        _, claude_mock = self._invoke(["usage", "limits", "--json"])
        claude_mock.assert_awaited_once_with(refresh=False)

    def test_one_reader_raising_does_not_crash_the_others(self):
        runner = CliRunner()
        with patch(
            "yagent.commands.usage._claude_reader.read_claude_provider",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ), patch(
            "yagent.commands.usage._http_readers.read_codex_provider",
            return_value=_codex_row(),
        ), patch(
            "yagent.commands.usage._http_readers.read_xai_provider",
            return_value=_xai_row(),
        ):
            result = runner.invoke(cli, ["usage", "limits", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        backends = sorted(p["backend"] for p in envelope["providers"])
        self.assertEqual(backends, ["codex", "grok"])
        self.assertEqual(len(envelope["errors"]), 1)
        self.assertEqual(envelope["errors"][0]["origin"], "claude_tui_usage")

    def test_table_output_does_not_crash_on_unavailable_and_billing_period_rows(self):
        runner = CliRunner()
        with patch(
            "yagent.commands.usage._claude_reader.read_claude_provider",
            new=AsyncMock(return_value=_claude_row(
                availability="reauth_required", error="reauth_required",
                windows={}, extra_windows={},
            )),
        ), patch(
            "yagent.commands.usage._http_readers.read_codex_provider",
            return_value=_codex_row(),
        ), patch(
            "yagent.commands.usage._http_readers.read_xai_provider",
            return_value=_xai_row(),
        ):
            result = runner.invoke(cli, ["usage", "limits"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("anthropic", result.output)
        self.assertIn("Billing period", result.output)


if __name__ == "__main__":
    unittest.main()
