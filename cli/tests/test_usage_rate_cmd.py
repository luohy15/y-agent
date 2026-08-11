import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from yagent.command_option import cli


class UsageRateCommandTest(unittest.TestCase):
    def test_json_delegates_to_read_rate(self):
        envelope = {
            "rpm": 2.5,
            "tpm": 123456,
            "window_minutes": 5,
            "is_historical": False,
            "observed_at": "2026-08-11T00:00:00Z",
            "error": None,
        }
        with (
            patch(
                "yagent.commands.usage.rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value=85),
            patch("yagent.commands.usage.rate.rate_service.read_rate", return_value=envelope) as read_rate,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output), envelope)
        read_rate.assert_called_once_with(85)

    def test_missing_credentials_returns_closed_not_configured_error(self):
        envelope = {
            "rpm": None,
            "tpm": None,
            "window_minutes": None,
            "is_historical": None,
            "observed_at": "2026-08-11T00:00:00Z",
            "error": "not_configured",
        }
        with (
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value=85),
            patch("yagent.commands.usage.rate.rate_service.read_rate", return_value=envelope),
            patch(
                "yagent.commands.usage.rate.usage_service._crs_admin_creds",
                side_effect=RuntimeError("credentials missing"),
            ),
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["error"], "not_configured")
        self.assertIsNone(payload["rpm"])

    def test_missing_db_and_credentials_returns_closed_not_configured_error(self):
        """CI regression: get_cli_user_id must not run ahead of the closed
        not_configured path when neither a database user nor local CRS creds
        are available (plan 3121 / review round 5)."""
        with (
            patch(
                "yagent.commands.usage.rate.get_cli_user_id",
                side_effect=RuntimeError("Database not initialized"),
            ) as get_user,
            patch(
                "yagent.commands.usage.rate.usage_service._crs_admin_creds",
                side_effect=RuntimeError("credentials missing"),
            ),
            patch("yagent.commands.usage.rate.rate_service.read_rate") as read_rate,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["error"], "not_configured")
        self.assertIsNone(payload["rpm"])
        self.assertEqual(
            set(payload),
            {"rpm", "tpm", "window_minutes", "is_historical", "observed_at", "error"},
        )
        get_user.assert_called_once()
        read_rate.assert_not_called()

    def test_text_output_formats_rpm_tpm(self):
        envelope = {
            "rpm": 2.5,
            "tpm": 123456.0,
            "window_minutes": 5,
            "is_historical": False,
            "observed_at": "2026-08-11T00:00:00Z",
            "error": None,
        }
        with (
            patch(
                "yagent.commands.usage.rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value=85),
            patch("yagent.commands.usage.rate.rate_service.read_rate", return_value=envelope),
        ):
            result = CliRunner().invoke(cli, ["usage", "rate"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("2.5 RPM", result.output)
        self.assertIn("123456.0 TPM", result.output)
        self.assertIn("5 minutes", result.output)

    def test_store_flag_is_gone(self):
        result = CliRunner().invoke(cli, ["usage", "rate", "--store", "--json"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such option", result.output)


class UsageCrsCredsCommandTest(unittest.TestCase):
    def test_set_upserts_from_env_or_config_without_argv_secret(self):
        with (
            patch(
                "yagent.commands.usage.crs_creds.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch("yagent.commands.usage.crs_creds.get_cli_user_id", return_value=85),
            patch(
                "yagent.commands.usage.crs_creds.user_pref_service.upsert_preference",
            ) as upsert,
        ):
            result = CliRunner().invoke(cli, ["usage", "crs-creds", "set"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("stored", result.output.lower())
        upsert.assert_called_once_with(85, "crs_admin", {
            "username": "admin",
            "password": "secret",
            "session_token": None,
            "token_expires_at": None,
        })

    def test_show_prints_username_and_password_set_without_secret(self):
        pref = type("P", (), {"value": {
            "username": "admin",
            "password": "super-secret",
            "session_token": "tok",
            "token_expires_at": "2026-08-12T00:00:00Z",
        }})()
        with (
            patch("yagent.commands.usage.crs_creds.get_cli_user_id", return_value=85),
            patch(
                "yagent.commands.usage.crs_creds.user_pref_service.get_preference",
                return_value=pref,
            ),
        ):
            result = CliRunner().invoke(cli, ["usage", "crs-creds", "show"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("username: admin", result.output)
        self.assertIn("password: set", result.output)
        self.assertNotIn("super-secret", result.output)
        self.assertNotIn("tok", result.output)

    def test_show_reports_not_configured(self):
        with (
            patch("yagent.commands.usage.crs_creds.get_cli_user_id", return_value=85),
            patch(
                "yagent.commands.usage.crs_creds.user_pref_service.get_preference",
                return_value=None,
            ),
        ):
            result = CliRunner().invoke(cli, ["usage", "crs-creds", "show"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("not configured", result.output.lower())


if __name__ == "__main__":
    unittest.main()
