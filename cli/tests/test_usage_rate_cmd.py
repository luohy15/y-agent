import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from yagent.command_option import cli


class UsageRateCommandTest(unittest.TestCase):
    def test_json_reads_dashboard_realtime_metrics(self):
        dashboard = {
            "data": {
                "realtimeMetrics": {
                    "rpm": 2.5,
                    "tpm": 123456,
                    "windowMinutes": 5,
                    "isHistorical": False,
                }
            }
        }
        with (
            patch("yagent.commands.usage.rate.usage_service._crs_admin_creds", return_value=("user", "password")),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value="user-id"),
            patch("yagent.commands.usage.rate.usage_service._crs_origin", return_value="https://relay.example") as origin,
            patch("yagent.commands.usage.rate.usage_service.crs_admin_login", return_value="token") as login,
            patch("yagent.commands.usage.rate.usage_service.crs_admin_get", return_value=dashboard) as get,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(envelope["rpm"], 2.5)
        self.assertEqual(envelope["tpm"], 123456)
        self.assertEqual(envelope["window_minutes"], 5)
        self.assertFalse(envelope["is_historical"])
        self.assertIsNone(envelope["error"])
        origin.assert_called_once_with("user-id")
        login.assert_called_once_with("https://relay.example", "user", "password")
        get.assert_called_once_with("https://relay.example", "/admin/dashboard", "token")

    def test_historical_dashboard_preserves_zero_minute_window(self):
        dashboard = {
            "data": {
                "realtimeMetrics": {
                    "rpm": 1.2,
                    "tpm": 3400,
                    "windowMinutes": 0,
                    "isHistorical": True,
                }
            }
        }
        with (
            patch("yagent.commands.usage.rate.usage_service._crs_admin_creds", return_value=("user", "password")),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value="user-id"),
            patch("yagent.commands.usage.rate.usage_service._crs_origin", return_value="https://relay.example"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_login", return_value="token"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_get", return_value=dashboard),
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(envelope["window_minutes"], 0)
        self.assertTrue(envelope["is_historical"])
        self.assertIsNone(envelope["error"])

    def test_missing_credentials_returns_closed_not_configured_error(self):
        with patch(
            "yagent.commands.usage.rate.usage_service._crs_admin_creds",
            side_effect=RuntimeError("credentials missing"),
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(envelope["error"], "not_configured")
        self.assertIsNone(envelope["rpm"])

    def test_malformed_dashboard_returns_parse_failed(self):
        with (
            patch("yagent.commands.usage.rate.usage_service._crs_admin_creds", return_value=("user", "password")),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value="user-id"),
            patch("yagent.commands.usage.rate.usage_service._crs_origin", return_value="https://relay.example"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_login", return_value="token"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_get", return_value={"data": {}}),
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output)["error"], "parse_failed")

    def test_without_store_flag_never_persists(self):
        dashboard = {
            "data": {
                "realtimeMetrics": {"rpm": 2.5, "tpm": 123456, "windowMinutes": 5, "isHistorical": False}
            }
        }
        with (
            patch("yagent.commands.usage.rate.usage_service._crs_admin_creds", return_value=("user", "password")),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value="user-id"),
            patch("yagent.commands.usage.rate.usage_service._crs_origin", return_value="https://relay.example"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_login", return_value="token"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_get", return_value=dashboard),
            patch("yagent.commands.usage.rate.rate_storage.store_reading") as store_reading,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        store_reading.assert_not_called()

    def test_store_flag_persists_the_envelope_under_the_cli_user_id(self):
        dashboard = {
            "data": {
                "realtimeMetrics": {"rpm": 2.5, "tpm": 123456, "windowMinutes": 5, "isHistorical": False}
            }
        }
        with (
            patch("yagent.commands.usage.rate.usage_service._crs_admin_creds", return_value=("user", "password")),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value=85),
            patch("yagent.commands.usage.rate.usage_service._crs_origin", return_value="https://relay.example"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_login", return_value="token"),
            patch("yagent.commands.usage.rate.usage_service.crs_admin_get", return_value=dashboard),
            patch("yagent.commands.usage.rate.rate_storage.store_reading") as store_reading,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--store", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(envelope["rpm"], 2.5)
        store_reading.assert_called_once_with(85, envelope)

    def test_store_flag_persists_a_failed_read_too(self):
        with (
            patch(
                "yagent.commands.usage.rate.usage_service._crs_admin_creds",
                side_effect=RuntimeError("credentials missing"),
            ),
            patch("yagent.commands.usage.rate.get_cli_user_id", return_value=85),
            patch("yagent.commands.usage.rate.rate_storage.store_reading") as store_reading,
        ):
            result = CliRunner().invoke(cli, ["usage", "rate", "--store", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        envelope = json.loads(result.output)
        self.assertEqual(envelope["error"], "not_configured")
        store_reading.assert_called_once_with(85, envelope)


if __name__ == "__main__":
    unittest.main()
